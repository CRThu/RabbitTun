import pytest
import socket
import threading
import time
import queue
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class FakePhy:
    def __init__(self):
        self._rx: queue.Queue = queue.Queue()

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
        return "FakePhy"


def make_pair():
    a = FakePhy()
    b = FakePhy()
    a.send = lambda data: b._rx.put(data)
    b.send = lambda data: a._rx.put(data)
    return a, b


def test_tunnel_frame():
    from tunnel.tunnel import Tunnel
    from tunnel.frame import TYPE_DATA
    phy_a, phy_b = make_pair()
    tun_a, tun_b = Tunnel(phy_a), Tunnel(phy_b)
    tun_a.open()
    tun_b.open()
    try:
        tun_a.send(b"HelloFrame")
        frame = tun_b.recv(timeout=3)
        assert frame == (TYPE_DATA, 0, b"HelloFrame")
    finally:
        tun_a.close()
        tun_b.close()


def test_tunnel_bidirectional():
    from tunnel.tunnel import Tunnel
    from tunnel.frame import TYPE_DATA
    phy_a, phy_b = make_pair()
    tun_a, tun_b = Tunnel(phy_a), Tunnel(phy_b)
    tun_a.open()
    tun_b.open()
    try:
        tun_a.send(b"request")
        tun_b.send(b"response")
        assert tun_b.recv(timeout=3) == (TYPE_DATA, 0, b"request")
        assert tun_a.recv(timeout=3) == (TYPE_DATA, 0, b"response")
    finally:
        tun_a.close()
        tun_b.close()


def test_tunnel_listen_and_target():
    from tunnel.tunnel import Tunnel
    from tunnel.cli import run_listen, run_target

    phy_a, phy_b = make_pair()
    tun_listen, tun_target = Tunnel(phy_a), Tunnel(phy_b)
    tun_listen.open()
    tun_target.open()

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

    listen_port = 18080
    threading.Thread(target=run_listen, args=(tun_listen, listen_port), daemon=True).start()
    threading.Thread(target=run_target, args=(tun_target, f"127.0.0.1:{echo_port}"), daemon=True).start()
    time.sleep(1)

    try:
        s = socket.create_connection(("127.0.0.1", listen_port), timeout=5)
        s.settimeout(5)
        s.sendall(b"tunnel_test")
        time.sleep(1)
        data = s.recv(4096)
        assert data == b"tunnel_test"
        assert b"tunnel_test" in echo_data
        s.close()
    finally:
        phy_a.close()
        phy_b.close()
        echo_srv.close()


def test_tunnel_target_reconnect():
    from tunnel.tunnel import Tunnel
    from tunnel.cli import run_target

    phy_a, phy_b = make_pair()
    tun, tun_b = Tunnel(phy_a), Tunnel(phy_b)
    tun.open()
    tun_b.open()

    target_port = 18090
    threading.Thread(target=run_target, args=(tun, f"127.0.0.1:{target_port}"), daemon=True).start()
    time.sleep(1)

    target_srv = socket.socket()
    target_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    target_srv.bind(("127.0.0.1", target_port))
    target_srv.listen(1)
    target_srv.settimeout(5)

    try:
        c, _ = target_srv.accept()
        c.settimeout(3)
        c.sendall(b"reconnect_ok")
        time.sleep(0.5)
        from tunnel.frame import TYPE_DATA
        assert tun_b.recv(timeout=3) == (TYPE_DATA, 0, b"reconnect_ok")
        c.close()
    finally:
        phy_a.close()
        target_srv.close()
