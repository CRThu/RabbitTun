"""Serial-port layer tests — run against real COM3 ↔ COM18."""
import pytest
import socket
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

COM_A = os.environ.get("TEST_COM_A", "COM3")
COM_B = os.environ.get("TEST_COM_B", "COM18")

try:
    import serial
    s = serial.Serial(COM_A, 115200, timeout=0.1)
    s.close()
    HAS_SERIAL = True
except Exception:
    HAS_SERIAL = False

pytestmark = pytest.mark.skipif(not HAS_SERIAL, reason="Serial ports not available")


@pytest.fixture(scope="module")
def serial_pair():
    from tunnel.phy.serial_phy import SerialPhy
    a = SerialPhy(COM_A, 115200)
    b = SerialPhy(COM_B, 115200)
    a.open()
    b.open()
    yield a, b
    a.close()
    b.close()


# ── Layer 1: raw serial loopback ──

def test_serial_loopback(serial_pair):
    a, b = serial_pair
    payload = b"HelloSerial"
    a.send(payload)
    deadline = time.time() + 3
    got = b""
    while time.time() < deadline:
        chunk = b.recv(4096)
        if chunk:
            got += chunk
        else:
            time.sleep(0.05)
    assert got == payload


# ── Layer 2: Tunnel frame encode/decode ──

def test_tunnel_frame(serial_pair):
    from tunnel.tunnel import Tunnel
    a, b = serial_pair
    tun_a = Tunnel(a)
    tun_b = Tunnel(b)
    tun_a.open()
    tun_b.open()
    try:
        payload = b"HelloFrame"
        tun_a.send(payload)
        got = tun_b.recv(timeout=3)
        assert got == payload
    finally:
        tun_a.close()
        tun_b.close()


# ── Layer 3: Tunnel bidirectional ──

def test_tunnel_bidirectional(serial_pair):
    from tunnel.tunnel import Tunnel
    a, b = serial_pair
    tun_a = Tunnel(a)
    tun_b = Tunnel(b)
    tun_a.open()
    tun_b.open()
    try:
        tun_a.send(b"request")
        tun_b.send(b"response")
        r1 = tun_b.recv(timeout=3)
        r2 = tun_a.recv(timeout=3)
        assert r1 == b"request"
        assert r2 == b"response"
    finally:
        tun_a.close()
        tun_b.close()


# ── Layer 4: Mux OPEN / OPEN_OK ──

def test_mux_open_roundtrip(serial_pair):
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    a, b = serial_pair
    tun_a = Tunnel(a)
    tun_b = Tunnel(b)
    tun_a.open()
    tun_b.open()

    mux_a = Mux(tun_a)
    mux_b = Mux(tun_b)

    opened = []

    def on_open(conn_id, target):
        opened.append((conn_id, target))
        mux_b.send_open_ok(conn_id)

    mux_b.on_open = on_open
    mux_b.start()
    mux_a.start()
    try:
        conn = mux_a.open("example.com:443", timeout=10)
        assert conn is not None
        assert len(opened) == 1
        assert opened[0][1] == "example.com:443"
    finally:
        mux_a.stop()
        mux_b.stop()
        tun_a.close()
        tun_b.close()


# ── Layer 5: Mux OPEN failure ──

def test_mux_open_fail(serial_pair):
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    a, b = serial_pair
    tun_a = Tunnel(a)
    tun_b = Tunnel(b)
    tun_a.open()
    tun_b.open()

    mux_a = Mux(tun_a)
    mux_b = Mux(tun_b)

    def on_open(conn_id, target):
        mux_b.send_open_fail(conn_id)

    mux_b.on_open = on_open
    mux_b.start()
    mux_a.start()
    try:
        conn = mux_a.open("unreachable:9999", timeout=5)
        assert conn is None
    finally:
        mux_a.stop()
        mux_b.stop()
        tun_a.close()
        tun_b.close()


# ── Layer 6: Mux DATA echo ──

def test_mux_data_echo(serial_pair):
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    a, b = serial_pair
    tun_a = Tunnel(a)
    tun_b = Tunnel(b)
    tun_a.open()
    tun_b.open()

    mux_a = Mux(tun_a)
    mux_b = Mux(tun_b)

    received = []

    def on_open(conn_id, target):
        mux_b.send_open_ok(conn_id)

        def on_data_cb(data):
            received.append(data)
            mux_b.send_data(conn_id, data)

        mux_b.on_data(conn_id, on_data_cb)

    mux_b.on_open = on_open
    mux_b.start()
    mux_a.start()
    try:
        conn = mux_a.open("echo:7", timeout=10)
        assert conn is not None

        conn.send(b"ping")
        time.sleep(3)
        got = conn.recv(timeout=5)
        assert got == b"ping"
        assert received == [b"ping"]
    finally:
        mux_a.stop()
        mux_b.stop()
        tun_a.close()
        tun_b.close()


# ── Layer 8: Full proxy → relay → echo server ──

def test_proxy_relay_e2e(serial_pair):
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    from tunnel.proxy.server import ProxyServer
    from tunnel.proxy.relay import RelayServer

    PROXY_PORT = 10840
    ECHO_PORT = 10841

    echo_data = []

    def echo_handler(client):
        try:
            while True:
                d = client.recv(4096)
                if not d:
                    break
                echo_data.append(d)
                client.sendall(d)
        except OSError:
            pass
        client.close()

    echo_srv = socket.socket()
    echo_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    echo_srv.bind(("127.0.0.1", ECHO_PORT))
    echo_srv.listen(5)
    echo_srv.settimeout(20)

    def accept_echo():
        try:
            while True:
                c, _ = echo_srv.accept()
                threading.Thread(target=echo_handler, args=(c,), daemon=True).start()
        except (socket.timeout, OSError):
            pass

    threading.Thread(target=accept_echo, daemon=True).start()

    a, b = serial_pair
    tun_a = Tunnel(a)
    tun_b = Tunnel(b)
    tun_a.open()
    tun_b.open()

    mux_a = Mux(tun_a)
    mux_b = Mux(tun_b)
    mux_b.start()
    mux_a.start()

    relay = RelayServer(mux_b)

    proxy = ProxyServer(mux_a, "127.0.0.1", PROXY_PORT)
    proxy_thread = threading.Thread(target=proxy.serve, daemon=True)
    proxy_thread.start()
    time.sleep(1)

    try:
        s = socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=10)
        s.settimeout(10)

        # SOCKS5 handshake
        s.sendall(b"\x05\x01\x00")
        assert s.recv(2) == b"\x05\x00"

        # SOCKS5 CONNECT to echo server
        target = socket.inet_aton("127.0.0.1") + ECHO_PORT.to_bytes(2, "big")
        s.sendall(b"\x05\x01\x00\x01" + target)
        resp = s.recv(10)
        assert resp[1] == 0x00

        # Send and receive through tunnel
        s.sendall(b"serial_e2e!")
        time.sleep(3)
        data = s.recv(4096)
        assert data == b"serial_e2e!"
        assert b"serial_e2e!" in echo_data

        s.close()
    finally:
        proxy.stop()
        mux_a.stop()
        mux_b.stop()
        tun_a.close()
        tun_b.close()
        echo_srv.close()
