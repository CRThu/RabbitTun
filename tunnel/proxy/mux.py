import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

OPEN = 0x01
OPEN_OK = 0x02
OPEN_FAIL = 0x03
DATA = 0x04
CLOSE = 0x05

_MAX_CONN = 128


class MuxConn:
    """A single logical connection multiplexed over a Tunnel."""

    def __init__(self, conn_id: int, mux: "Mux") -> None:
        self.conn_id = conn_id
        self._mux = mux
        self._rx: queue.Queue[bytes | None] = queue.Queue()
        self._closed = False

    def send(self, data: bytes) -> None:
        self._mux._send(self.conn_id, DATA, data)

    def recv(self, timeout: float | None = 5.0) -> bytes | None:
        if self._closed:
            return None
        try:
            data = self._rx.get(timeout=timeout)
            if data is None:
                self._closed = True
            return data
        except queue.Empty:
            raise TimeoutError

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._mux._send(self.conn_id, CLOSE)
            self._mux._forget(self.conn_id)

    def _feed_data(self, data: bytes) -> None:
        self._rx.put(data)

    def _feed_close(self) -> None:
        self._rx.put(None)

    def __enter__(self) -> "MuxConn":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class Mux:
    """Multiplexes a single Tunnel into multiple logical connections.

    A single reader thread owns Tunnel.recv().  Incoming frames are
    dispatched by connection-id to either a MuxConn (on the proxy side)
    or registered callbacks (on the relay side).
    """

    def __init__(self, tunnel: "Tunnel") -> None:
        self._tunnel = tunnel
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conns: dict[int, MuxConn] = {}
        self._pending_open: dict[int, queue.SimpleQueue[bool]] = {}
        self._data_cbs: dict[int, Callable[[bytes], None]] = {}
        self._close_cbs: dict[int, Callable[[], None]] = {}
        self._next_id = 0
        self.on_open: Callable[[int, str], None] | None = None

    # ── lifecycle ──────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── low-level send ─────────────────────────────────────────

    def _send(self, conn_id: int, ftype: int, payload: bytes = b"") -> None:
        with self._send_lock:
            self._tunnel.send(bytes([conn_id, ftype]) + payload)

    # ── entry (proxy) side: open a new connection through the tunnel ──

    def open(self, target: str, timeout: float = 15.0) -> MuxConn | None:
        conn_id = self._alloc_id()
        q: queue.SimpleQueue[bool] = queue.SimpleQueue()
        conn = MuxConn(conn_id, self)
        with self._lock:
            self._conns[conn_id] = conn
            self._pending_open[conn_id] = q
        self._send(conn_id, OPEN, target.encode("utf-8"))

        try:
            ok = q.get(timeout=timeout)
            if ok:
                return conn
        except queue.Empty:
            pass

        with self._lock:
            self._conns.pop(conn_id, None)
            self._pending_open.pop(conn_id, None)
        return None

    def _alloc_id(self) -> int:
        with self._lock:
            for _ in range(_MAX_CONN):
                cid = self._next_id
                self._next_id = (cid + 1) % _MAX_CONN
                if cid not in self._conns:
                    return cid
            raise RuntimeError("no free connection id")

    def _forget(self, conn_id: int) -> None:
        with self._lock:
            self._conns.pop(conn_id, None)
            self._data_cbs.pop(conn_id, None)
            self._close_cbs.pop(conn_id, None)

    # ── exit (relay) side: register callbacks ──────────────────

    def on_data(self, conn_id: int, cb: Callable[[bytes], None]) -> None:
        with self._lock:
            self._data_cbs[conn_id] = cb

    def on_close(self, conn_id: int, cb: Callable[[], None]) -> None:
        with self._lock:
            self._close_cbs[conn_id] = cb

    def send_open_ok(self, conn_id: int) -> None:
        self._send(conn_id, OPEN_OK)

    def send_open_fail(self, conn_id: int) -> None:
        self._send(conn_id, OPEN_FAIL)

    def send_data(self, conn_id: int, data: bytes) -> None:
        self._send(conn_id, DATA, data)

    def send_close(self, conn_id: int) -> None:
        self._send(conn_id, CLOSE)

    # ── reader / dispatcher ────────────────────────────────────

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            raw = self._tunnel.recv(timeout=0.5)
            if raw is None or len(raw) < 2:
                continue
            self._dispatch(raw[0], raw[1], raw[2:])

    def _dispatch(self, conn_id: int, ftype: int, payload: bytes) -> None:
        if ftype == OPEN:
            target = payload.decode("utf-8", errors="replace")
            if self.on_open:
                self.on_open(conn_id, target)

        elif ftype == OPEN_OK:
            with self._lock:
                q = self._pending_open.pop(conn_id, None)
            if q:
                q.put(True)

        elif ftype == OPEN_FAIL:
            with self._lock:
                q = self._pending_open.pop(conn_id, None)
                self._conns.pop(conn_id, None)
            if q:
                q.put(False)

        elif ftype == DATA:
            with self._lock:
                conn = self._conns.get(conn_id)
                if conn:
                    conn._feed_data(payload)
                    return
                cb = self._data_cbs.get(conn_id)
            if cb:
                cb(payload)

        elif ftype == CLOSE:
            with self._lock:
                conn = self._conns.pop(conn_id, None)
            if conn:
                conn._feed_close()
                return
            with self._lock:
                cb = self._close_cbs.get(conn_id)
            if cb:
                cb()
                self._forget(conn_id)
