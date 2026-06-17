import logging
import socket
import threading

from .mux import Mux, MuxConn

logger = logging.getLogger(__name__)


def _read_n(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf.extend(chunk)
    return bytes(buf)


def _send_socks5_reply(sock: socket.socket, code: int) -> None:
    sock.sendall(bytes([0x05, code, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))


def _bridge(mux_conn: MuxConn, tcp_conn: socket.socket) -> None:
    stop = threading.Event()

    def to_mux() -> None:
        while not stop.is_set():
            try:
                data = tcp_conn.recv(65536)
                if not data:
                    break
                mux_conn.send(data)
            except (socket.timeout, OSError):
                break
        stop.set()
        mux_conn.close()

    def from_mux() -> None:
        while not stop.is_set():
            try:
                data = mux_conn.recv(timeout=0.5)
            except TimeoutError:
                continue
            if data is None:
                break
            try:
                tcp_conn.sendall(data)
            except OSError:
                break
        stop.set()

    threads = [threading.Thread(target=t, daemon=True) for t in (to_mux, from_mux)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300.0)
    stop.set()


class ProxyServer:
    """SOCKS5 + HTTP CONNECT proxy (entry side).

    Listens on a TCP port, auto-detects SOCKS5 and HTTP CONNECT
    protocols, then proxies through the tunnel via *mux*.
    """

    def __init__(self, mux: Mux, host: str = "127.0.0.1", port: int = 1080) -> None:
        self._mux = mux
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stop = threading.Event()

    def serve(self) -> None:
        self._sock.bind((self._host, self._port))
        self._sock.listen(10)
        self._sock.settimeout(1.0)
        logger.info("Proxy listening on %s:%d (SOCKS5 + HTTP CONNECT)", self._host, self._port)

        try:
            while not self._stop.is_set():
                try:
                    client, addr = self._sock.accept()
                    logger.debug("Client connected: %s", addr)
                    threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            pass
        finally:
            self._sock.close()

    def stop(self) -> None:
        self._stop.set()

    # ── client handling ────────────────────────────────────────

    def _handle_client(self, client: socket.socket) -> None:
        client.settimeout(15.0)
        try:
            first = _read_n(client, 1)
            if first == b"\x05":
                self._socks5(client)
            elif first in (b"C", b"c"):
                self._http_connect(client, first)
        except (OSError, ConnectionError):
            logger.debug("Proxy client disconnected", exc_info=True)
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _socks5(self, client: socket.socket) -> None:
        nmethods = _read_n(client, 1)[0]
        if nmethods > 0:
            _read_n(client, nmethods)
        client.sendall(b"\x05\x00")

        ver_cmd_rsv = _read_n(client, 3)
        if ver_cmd_rsv[1] != 0x01:  # only CONNECT
            _send_socks5_reply(client, 0x07)
            return

        atype = _read_n(client, 1)[0]
        host = self._parse_addr(client, atype)
        if host is None:
            _send_socks5_reply(client, 0x08)
            return

        port = int.from_bytes(_read_n(client, 2), "big")
        target = f"{host}:{port}"

        mux_conn = self._mux.open(target)
        if mux_conn is None:
            _send_socks5_reply(client, 0x04)
            return

        _send_socks5_reply(client, 0x00)
        _bridge(mux_conn, client)

    def _http_connect(self, client: socket.socket, first: bytes) -> None:
        data = first
        while b"\r\n\r\n" not in data:
            chunk = client.recv(4096)
            if not chunk:
                return
            data += chunk
            if len(data) > 65536:
                return

        line = data.split(b"\r\n")[0]
        parts = line.split(b" ")
        if len(parts) < 3 or parts[0].upper() != b"CONNECT":
            return

        host_port = parts[1].decode("ascii", errors="replace")
        host, port_str = host_port.rsplit(":", 1)
        target = f"{host}:{int(port_str)}"

        mux_conn = self._mux.open(target)
        if mux_conn is None:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return

        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        _bridge(mux_conn, client)

    @staticmethod
    def _parse_addr(sock: socket.socket, atype: int) -> str | None:
        try:
            if atype == 0x01:
                return socket.inet_ntoa(_read_n(sock, 4))
            elif atype == 0x03:
                dlen = _read_n(sock, 1)[0]
                return _read_n(sock, dlen).decode("ascii", errors="replace")
            elif atype == 0x04:
                return socket.inet_ntop(socket.AF_INET6, _read_n(sock, 16))
        except (OSError, ConnectionError):
            pass
        return None
