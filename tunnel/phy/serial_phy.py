import threading
import serial
from .base import PhysicalLayer


class SerialPhy(PhysicalLayer):
    def __init__(self, port: str, baudrate: int = 115200, read_timeout: float = 0.1):
        self._port = port
        self._baudrate = baudrate
        self._read_timeout = read_timeout
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        if self._ser and self._ser.is_open:
            return
        self._ser = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._read_timeout,
        )

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
            if not self._ser:
                return b''
            return self._ser.read(4096)

    @property
    def name(self) -> str:
        return f'{type(self).__name__}({self._port}, {self._baudrate})'
