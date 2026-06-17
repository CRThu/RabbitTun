from abc import ABC, abstractmethod
import socket
import threading


class Phy(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send(self, data: bytes) -> None: ...

    @abstractmethod
    def recv(self, timeout: float | None = None) -> bytes: ...


class SerialPhy(Phy):
    def __init__(self, port: str, baudrate: int = 115200):
        self._port = port
        self._baudrate = baudrate
        self._ser = None
        self._lock = threading.Lock()

    def open(self) -> None:
        import serial
        self._ser = serial.Serial(port=self._port, baudrate=self._baudrate, timeout=0.1)

    def close(self) -> None:
        with self._lock:
            if self._ser and self._ser.is_open:
                self._ser.close()
            self._ser = None

    def send(self, data: bytes) -> None:
        with self._lock:
            if self._ser:
                self._ser.write(data)

    def recv(self, timeout: float | None = None) -> bytes:
        with self._lock:
            return self._ser.read(4096) if self._ser else b''

    @property
    def name(self) -> str:
        return f'{self._port}@{self._baudrate}'


class TcpPhy(Phy):
    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None

    def open(self) -> None:
        self._sock = socket.create_connection((self._host, self._port), timeout=5)

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
        except (socket.timeout, OSError):
            return b''

    @property
    def name(self) -> str:
        return f'{self._host}:{self._port}'
