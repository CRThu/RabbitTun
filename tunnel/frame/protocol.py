import logging

from .crc import crc16_modbus

logger = logging.getLogger(__name__)

HEAD = 0x7E
TAIL = 0x7F
MAX_PAYLOAD = 4096


def encode(payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f'payload too large: {len(payload)} > {MAX_PAYLOAD}')
    hdr = len(payload).to_bytes(2, 'big') + payload
    crc = crc16_modbus(hdr)
    return bytes([HEAD]) + hdr + crc.to_bytes(2, 'little') + bytes([TAIL])


class Decoder:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        frames: list[bytes] = []

        while True:
            start = self._buf.find(bytes([HEAD]))
            if start < 0:
                self._buf.clear()
                break

            if start > 0:
                del self._buf[:start]

            if len(self._buf) < 6:
                break

            pkt_len = int.from_bytes(self._buf[1:3], 'big')
            if pkt_len > MAX_PAYLOAD:
                del self._buf[:1]
                continue

            total = 3 + pkt_len + 2 + 1  # HEAD + len + payload + crc + TAIL
            if len(self._buf) < total:
                break

            if self._buf[total - 1] != TAIL:
                del self._buf[:1]
                continue

            raw = bytes(self._buf[1:total - 1])
            recv_crc = int.from_bytes(raw[-2:], 'little')

            if crc16_modbus(raw[:-2]) != recv_crc:
                del self._buf[:1]
                continue

            frames.append(raw[2:-2])
            del self._buf[:total]

        return frames
