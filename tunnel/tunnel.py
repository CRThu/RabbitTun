from .phy import Phy
from .frame import encode, Decoder, MAX_PAYLOAD


class Tunnel:
    __slots__ = ('_phy', '_decoder', '_pending')

    def __init__(self, phy: Phy):
        self._phy = phy
        self._decoder = Decoder()
        self._pending: list[bytes] = []

    def open(self) -> None:
        self._phy.open()

    def close(self) -> None:
        self._phy.close()

    def send(self, data: bytes) -> None:
        enc = encode
        phy_send = self._phy.send
        for i in range(0, len(data), MAX_PAYLOAD):
            phy_send(enc(data[i:i + MAX_PAYLOAD]))

    def recv(self, timeout: float | None = None) -> bytes | None:
        pending = self._pending
        while not pending:
            raw = self._phy.recv(timeout)
            if not raw:
                return None
            pending.extend(self._decoder.feed(raw))
        return pending.pop(0)
