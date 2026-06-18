import pytest
import socket
import threading
import time
import sys
import os
import serial
import serial.tools.list_ports

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def find_serial_pair():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    for a, b in [("COM3", "COM18"), ("COM4", "COM18")]:
        if a in ports and b in ports:
            return a, b
    pytest.skip("No serial pair found")


def _read_one(tun, sid, timeout=3):
    q = tun.register(sid)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if q:
                return q.popleft()
            time.sleep(0.001)
        return None
    finally:
        tun.unregister(sid)


@pytest.fixture
def serial_pair():
    port_a, port_b = find_serial_pair()
    from tunnel.tunnel import Tunnel
    from tunnel.phy import SerialPhy

    tun_a, tun_b = Tunnel(SerialPhy(port_a)), Tunnel(SerialPhy(port_b))
    tun_a.open()
    tun_b.open()
    yield tun_a, tun_b
    tun_a.close()
    tun_b.close()


def test_tunnel_frame_serial(serial_pair):
    from tunnel.frame import TYPE_DATA
    tun_a, tun_b = serial_pair
    tun_a.send(0, b"HelloSerial")
    assert _read_one(tun_b, 0) == (TYPE_DATA, b"HelloSerial")


def test_tunnel_bidirectional_serial(serial_pair):
    from tunnel.frame import TYPE_DATA
    tun_a, tun_b = serial_pair
    tun_a.send(0, b"request")
    time.sleep(0.1)
    tun_b.send(0, b"response")
    assert _read_one(tun_b, 0) == (TYPE_DATA, b"request")
    assert _read_one(tun_a, 0) == (TYPE_DATA, b"response")


def test_tunnel_listen_and_target_serial(serial_pair):
    from tunnel.cli import run_listen, run_target

    tun_listen, tun_target = serial_pair

    echo_srv = socket.socket()
    echo_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    echo_srv.bind(("127.0.0.1", 0))
    echo_port = echo_srv.getsockname()[1]
    echo_srv.listen(5)
    echo_srv.settimeout(10)
    echo_data = []

    def echo_handler():
        try:
            while True:
                c, _ = echo_srv.accept()
                while True:
                    d = c.recv(4096)
                    if not d:
                        break
                    echo_data.append(d)
                    c.sendall(d)
                c.close()
        except (socket.timeout, OSError):
            pass

    threading.Thread(target=echo_handler, daemon=True).start()

    listen_port = 18081
    threading.Thread(target=run_listen, args=(tun_listen, listen_port), daemon=True).start()
    threading.Thread(target=run_target, args=(tun_target, f"127.0.0.1:{echo_port}"), daemon=True).start()
    time.sleep(2)

    try:
        s = socket.create_connection(("127.0.0.1", listen_port), timeout=5)
        s.settimeout(5)
        s.sendall(b"serial_tunnel_test")
        time.sleep(2)
        data = s.recv(4096)
        assert data == b"serial_tunnel_test"
        assert b"serial_tunnel_test" in echo_data
        s.close()
    finally:
        echo_srv.close()
