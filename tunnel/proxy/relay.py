import logging
import socket
import threading

from .mux import Mux

logger = logging.getLogger(__name__)


class RelayServer:
    """TCP relay (exit side).

    Receives OPEN frames from the tunnel, connects to the real target
    host, and bridges data bidirectionally.
    """

    def __init__(self, mux: Mux) -> None:
        self._mux = mux
        mux.on_open = self._on_open

    def _on_open(self, conn_id: int, target: str) -> None:
        logger.debug("Relay OPEN %s (id=%d)", target, conn_id)
        threading.Thread(target=self._handle, args=(conn_id, target), daemon=True).start()

    def _handle(self, conn_id: int, target: str) -> None:
        host, port_str = target.rsplit(":", 1)
        port = int(port_str)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)

        try:
            sock.connect((host, port))
        except (OSError, socket.timeout) as e:
            logger.warning("Relay connect %s failed: %s", target, e)
            self._mux.send_open_fail(conn_id)
            sock.close()
            return

        self._mux.send_open_ok(conn_id)
        sock.settimeout(None)
        self._bridge(conn_id, sock)

    def _bridge(self, conn_id: int, sock: socket.socket) -> None:
        stop = threading.Event()

        def from_tunnel(data: bytes) -> None:
            try:
                sock.sendall(data)
            except OSError:
                stop.set()

        def tunnel_closed() -> None:
            stop.set()
            try:
                sock.close()
            except OSError:
                pass

        self._mux.on_data(conn_id, from_tunnel)
        self._mux.on_close(conn_id, tunnel_closed)

        while not stop.is_set():
            try:
                data = sock.recv(65536)
                if not data:
                    break
                self._mux.send_data(conn_id, data)
            except (socket.timeout, OSError):
                break

        stop.set()
        self._mux.send_close(conn_id)
        self._mux._forget(conn_id)
