from .phy.base import PhysicalLayer
from .frame.protocol import encode, Decoder


class Tunnel:
    def __init__(self, phy: PhysicalLayer):
        self._phy = phy
        self._decoder = Decoder()
        self._pending: list[bytes] = []

    def open(self) -> None:
        self._phy.open()

    def close(self) -> None:
        self._phy.close()

    def send(self, data: bytes) -> None:
        self._phy.send(encode(data))

    def recv(self, timeout: float | None = None) -> bytes | None:
        while not self._pending:
            raw = self._phy.recv(timeout)
            if not raw:
                return None
            self._pending = self._decoder.feed(raw)
        return self._pending.pop(0)
