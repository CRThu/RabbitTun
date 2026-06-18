import struct

HEAD = 0x7E
TAIL = 0x7F
MAX_PAYLOAD = 4096

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


# pre-allocate HEAD/TAIL bytes
_HEAD = bytes([HEAD])
_TAIL = bytes([TAIL])


def encode(payload: bytes) -> bytes:
    n = len(payload)
    if n > MAX_PAYLOAD:
        raise ValueError(f'payload too large: {n} > {MAX_PAYLOAD}')
    buf = bytearray(1 + 2 + n + 2 + 1)
    buf[0] = HEAD
    buf[1] = n >> 8
    buf[2] = n & 0xFF
    buf[3:3 + n] = payload
    crc = crc16_modbus(buf[1:3 + n])
    buf[3 + n] = crc & 0xFF
    buf[4 + n] = crc >> 8
    buf[5 + n] = TAIL
    return bytes(buf)


class Decoder:
    __slots__ = ('_buf',)

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        frames: list[bytes] = []
        buf = self._buf

        while True:
            start = buf.find(HEAD)
            if start < 0:
                buf.clear()
                break
            if start > 0:
                del buf[:start]
            if len(buf) < 6:
                break

            pkt_len = (buf[1] << 8) | buf[2]
            if pkt_len > MAX_PAYLOAD:
                del buf[:1]
                continue

            total = 3 + pkt_len + 2 + 1
            if len(buf) < total:
                break
            if buf[total - 1] != TAIL:
                del buf[:1]
                continue

            # verify CRC: buf[1:total-1] is (len_bytes + payload + crc_bytes)
            body_end = total - 1
            if crc16_modbus(bytes(buf[1:body_end - 2])) != (buf[body_end - 2] | (buf[body_end - 1] << 8)):
                del buf[:1]
                continue

            frames.append(bytes(buf[3:3 + pkt_len]))
            del buf[:total]

        return frames
