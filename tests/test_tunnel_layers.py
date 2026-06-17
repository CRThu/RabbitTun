import pytest
import socket
import threading
import time
import queue
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── FakePhy: in-process loopback for testing without hardware ──

class FakePhy:
    """In-process loopback physical layer using queues."""

    def __init__(self):
        self._rx: queue.Queue = queue.Queue()
        self._name = "FakePhy"

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def send(self, data: bytes) -> None:
        self._rx.put(data)

    def recv(self, timeout: float | None = None) -> bytes:
        try:
            return self._rx.get(timeout=timeout or 0.1)
        except queue.Empty:
            return b""

    @property
    def name(self) -> str:
        return self._name


def make_pair():
    """Create a pair of FakePhys wired together."""
    a = FakePhy()
    b = FakePhy()
    a.send_orig = a.send
    b.send_orig = b.send
    a_send_q = b._rx
    b_send_q = a._rx
    a.send = lambda data: a_send_q.put(data)
    b.send = lambda data: b_send_q.put(data)
    return a, b


# ── Layer 2: Tunnel frame encode/decode (FakePhy) ──

def test_tunnel_frame():
    from tunnel.tunnel import Tunnel
    phy_a, phy_b = make_pair()
    tun_a = Tunnel(phy_a)
    tun_b = Tunnel(phy_b)
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

def test_tunnel_bidirectional():
    from tunnel.tunnel import Tunnel
    phy_a, phy_b = make_pair()
    tun_a = Tunnel(phy_a)
    tun_b = Tunnel(phy_b)
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

def test_mux_open_roundtrip():
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    phy_a, phy_b = make_pair()
    tun_a = Tunnel(phy_a)
    tun_b = Tunnel(phy_b)
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

def test_mux_open_fail():
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    phy_a, phy_b = make_pair()
    tun_a = Tunnel(phy_a)
    tun_b = Tunnel(phy_b)
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

def test_mux_data_echo():
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    phy_a, phy_b = make_pair()
    tun_a = Tunnel(phy_a)
    tun_b = Tunnel(phy_b)
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
        time.sleep(2)
        got = conn.recv(timeout=3)
        assert got == b"ping"
        assert received == [b"ping"]
    finally:
        mux_a.stop()
        mux_b.stop()
        tun_a.close()
        tun_b.close()


# ── Layer 7: MuxConn.recv TimeoutError vs close ──

def test_mux_conn_recv_timeout_raises():
    from tunnel.proxy.mux import MuxConn, Mux

    class FakeTunnel:
        def send(self, data): pass
        def recv(self, timeout=0.1): return None
        def close(self): pass

    mux = Mux(FakeTunnel())
    conn = MuxConn(0, mux)
    with pytest.raises(TimeoutError):
        conn.recv(timeout=0.1)


def test_mux_conn_recv_close_returns_none():
    from tunnel.proxy.mux import MuxConn, Mux

    class FakeTunnel:
        def send(self, data): pass
        def recv(self, timeout=0.1): return None
        def close(self): pass

    mux = Mux(FakeTunnel())
    conn = MuxConn(0, mux)
    conn._feed_close()
    result = conn.recv(timeout=1)
    assert result is None
    assert conn._closed


# ── Layer 8: Full proxy → relay → echo server ──

def test_proxy_relay_e2e():
    from tunnel.tunnel import Tunnel
    from tunnel.proxy.mux import Mux
    from tunnel.proxy.server import ProxyServer
    from tunnel.proxy.relay import RelayServer

    PROXY_PORT = 10830
    ECHO_PORT = 10831

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
    echo_srv.settimeout(15)

    def accept_echo():
        try:
            while True:
                c, _ = echo_srv.accept()
                threading.Thread(target=echo_handler, args=(c,), daemon=True).start()
        except (socket.timeout, OSError):
            pass

    threading.Thread(target=accept_echo, daemon=True).start()

    phy_a, phy_b = make_pair()
    tun_a = Tunnel(phy_a)
    tun_b = Tunnel(phy_b)
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

        s.sendall(b"\x05\x01\x00")
        assert s.recv(2) == b"\x05\x00"

        target = socket.inet_aton("127.0.0.1") + ECHO_PORT.to_bytes(2, "big")
        s.sendall(b"\x05\x01\x00\x01" + target)
        resp = s.recv(10)
        assert resp[1] == 0x00

        s.sendall(b"pytest!")
        time.sleep(2)
        data = s.recv(4096)
        assert data == b"pytest!"
        assert b"pytest!" in echo_data

        s.close()
    finally:
        proxy.stop()
        mux_a.stop()
        mux_b.stop()
        tun_a.close()
        tun_b.close()
        echo_srv.close()
