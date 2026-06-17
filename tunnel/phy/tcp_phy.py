import socket

from .base import PhysicalLayer


class TcpPhy(PhysicalLayer):
    def __init__(self, host: str, port: int, connect_timeout: float = 5.0):
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None

    def open(self) -> None:
        if self._sock:
            return
        self._sock = socket.create_connection(
            (self._host, self._port),
            timeout=self._connect_timeout,
        )

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def send(self, data: bytes) -> None:
        if self._sock:
            self._sock.sendall(data)

    def recv(self, timeout: float | None = None) -> bytes:
        if not self._sock:
            return b''
        try:
            if timeout is not None:
                self._sock.settimeout(timeout)
                data = self._sock.recv(4096)
                self._sock.settimeout(None)
                return data
            return self._sock.recv(4096)
        except socket.timeout:
            return b''
        except OSError:
            return b''

    @property
    def name(self) -> str:
        return f'{type(self).__name__}({self._host}:{self._port})'
