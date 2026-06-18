from .phy import Phy
from .frame import encode, Decoder, MAX_PAYLOAD, TYPE_DATA, TYPE_OPEN, TYPE_CLOSE
import threading
from collections import deque


class Tunnel:
    __slots__ = ('_phy', '_decoder', '_queues', '_pending', '_all_q', '_lock', '_running')

    def __init__(self, phy: Phy):
        self._phy = phy
        self._decoder = Decoder()
        self._queues: dict[int, deque] = {}
        self._pending: dict[int, list] = {}
        self._all_q: deque = deque()
        self._lock = threading.Lock()
        self._running = False

    def open(self) -> None:
        self._phy.open()
        self._running = True
        threading.Thread(target=self._dispatch, daemon=True).start()

    def _dispatch(self) -> None:
        while self._running:
            raw = self._phy.recv(timeout=0.01)
            if not raw:
                continue
            for ftype, sid, data in self._decoder.feed(raw):
                if ftype != TYPE_DATA:
                    self._all_q.append((ftype, sid, data))
                with self._lock:
                    q = self._queues.get(sid)
                if q is not None:
                    q.append((ftype, data))
                elif ftype == TYPE_DATA:
                    with self._lock:
                        self._pending.setdefault(sid, []).append((ftype, data))

    def close(self) -> None:
        self._running = False
        self._phy.close()

    def register(self, sid: int) -> deque:
        q: deque = deque()
        with self._lock:
            self._queues[sid] = q
            for item in self._pending.pop(sid, []):
                q.append(item)
        return q

    def unregister(self, sid: int) -> None:
        with self._lock:
            self._queues.pop(sid, None)
            self._pending.pop(sid, None)

    def send(self, sid: int, data: bytes) -> None:
        enc = encode
        phy_send = self._phy.send
        for i in range(0, len(data), MAX_PAYLOAD):
            phy_send(enc(data[i:i + MAX_PAYLOAD], TYPE_DATA, sid))

    def send_frame(self, frame_type: int, sid: int, data: bytes = b'') -> None:
        self._phy.send(encode(data, frame_type, sid))
