import struct

HEAD = 0x7E
TAIL = 0x7F
MAX_PAYLOAD = 4096

# frame types
TYPE_DATA = 0x00
TYPE_OPEN = 0x01
TYPE_CLOSE = 0x02

# CRC16-MODBUS lookup table
_CRC_TABLE = []
for i in range(256):
    crc = i
    for _ in range(8):
        crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    _CRC_TABLE.append(crc)


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc = _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc


def encode(payload: bytes, frame_type: int = TYPE_DATA, sid: int = 0) -> bytes:
    n = len(payload)
    if n > MAX_PAYLOAD:
        raise ValueError(f'payload too large: {n} > {MAX_PAYLOAD}')
    # HEAD(1) + LEN(2) + TYPE(1) + SID(1) + DATA(n) + CRC(2) + TAIL(1)
    body_len = 2 + n  # TYPE + SID + DATA
    buf = bytearray(1 + 2 + body_len + 2 + 1)
    buf[0] = HEAD
    buf[1] = body_len >> 8
    buf[2] = body_len & 0xFF
    buf[3] = frame_type
    buf[4] = sid
    buf[5:5 + n] = payload
    crc = crc16_modbus(buf[1:5 + n])
    buf[5 + n] = crc & 0xFF
    buf[6 + n] = crc >> 8
    buf[7 + n] = TAIL
    return bytes(buf)


class Decoder:
    __slots__ = ('_buf',)

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        self._buf.extend(data)
        frames: list[tuple[int, int, bytes]] = []
        buf = self._buf

        while True:
            start = buf.find(HEAD)
            if start < 0:
                buf.clear()
                break
            if start > 0:
                del buf[:start]
            if len(buf) < 7:
                break

            body_len = (buf[1] << 8) | buf[2]
            if body_len < 2 or body_len > MAX_PAYLOAD + 2:
                del buf[:1]
                continue

            total = 1 + 2 + body_len + 2 + 1
            if len(buf) < total:
                break
            if buf[total - 1] != TAIL:
                del buf[:1]
                continue

            body_end = total - 1
            if crc16_modbus(bytes(buf[1:body_end - 2])) != (buf[body_end - 2] | (buf[body_end - 1] << 8)):
                del buf[:1]
                continue

            frame_type = buf[3]
            sid = buf[4]
            payload = bytes(buf[5:5 + body_len - 2])
            frames.append((frame_type, sid, payload))
            del buf[:total]

        return frames
