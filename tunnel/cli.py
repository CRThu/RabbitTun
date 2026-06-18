import argparse
import logging
import socket
import threading
import time

from .phy import SerialPhy, TcpPhy
from .tunnel import Tunnel
from .frame import TYPE_DATA, TYPE_OPEN, TYPE_CLOSE

logger = logging.getLogger(__name__)


def parse_phy(spec: str):
    if spec.startswith('tcp:'):
        rest = spec[4:]
        host, port = rest.rsplit(':', 1)
        return TcpPhy(host, int(port))
    if ':' in spec:
        port, baud = spec.rsplit(':', 1)
        return SerialPhy(port, int(baud))
    return SerialPhy(spec)


# ── pipe ─────────────────────────────────────────────────

def pipe(tun: Tunnel, conn: socket.socket, sid: int, q=None) -> None:
    if q is None:
        q = tun.register(sid)
    stop = threading.Event()

    def to_phy():
        while not stop.is_set():
            try:
                data = conn.recv(65536)
                if not data:
                    break
                tun.send(sid, data)
            except (socket.timeout, OSError):
                break
        stop.set()

    def from_phy():
        while not stop.is_set():
            if q:
                ftype, fdata = q.popleft()
                if ftype == TYPE_DATA and fdata:
                    try:
                        conn.sendall(fdata)
                    except OSError:
                        break
            else:
                time.sleep(0.001)
        stop.set()

    t1 = threading.Thread(target=to_phy, daemon=True)
    t2 = threading.Thread(target=from_phy, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    tun.unregister(sid)
    conn.close()


# ── listen ───────────────────────────────────────────────

def run_listen(tun: Tunnel, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(5)
    srv.settimeout(1.0)
    logger.info('listen :%d', port)

    sessions: dict[int, socket.socket] = {}
    lock = threading.Lock()
    next_sid = [1]

    try:
        while True:
            try:
                conn, addr = srv.accept()
                with lock:
                    sid = next_sid[0]
                    next_sid[0] = next_sid[0] % 255 + 1
                    sessions[sid] = conn
                logger.info('session %d from %s', sid, addr)
                tun.send_frame(TYPE_OPEN, sid)
                threading.Thread(target=_session_pipe, args=(tun, conn, sid, sessions, lock), daemon=True).start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


def _session_pipe(tun: Tunnel, conn: socket.socket, sid: int, sessions: dict, lock: threading.Lock) -> None:
    try:
        pipe(tun, conn, sid)
    finally:
        with lock:
            sessions.pop(sid, None)
        tun.send_frame(TYPE_CLOSE, sid)
        logger.info('session %d disconnected', sid)


# ── target ───────────────────────────────────────────────

def run_target(tun: Tunnel, target: str) -> None:
    host, port = target.rsplit(':', 1)
    logger.info('target %s:%s', host, port)

    sessions: dict[int, socket.socket] = {}
    lock = threading.Lock()

    def dispatcher():
        while True:
            if tun._all_q:
                ftype, sid, fdata = tun._all_q.popleft()
                if ftype == TYPE_OPEN:
                    # register queue immediately to buffer DATA frames
                    q = tun.register(sid)
                    try:
                        conn = socket.create_connection((host, int(port)), timeout=5)
                        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        with lock:
                            sessions[sid] = conn
                        logger.info('session %d connected to %s:%s', sid, host, port)
                        threading.Thread(target=_target_pipe, args=(tun, conn, sid, q, lock), daemon=True).start()
                    except (ConnectionRefusedError, OSError) as e:
                        logger.warning('session %d connect failed: %s', sid, e)
                        tun.unregister(sid)
                        tun.send_frame(TYPE_CLOSE, sid)
                elif ftype == TYPE_CLOSE:
                    with lock:
                        conn = sessions.pop(sid, None)
                    if conn:
                        try:
                            conn.close()
                        except OSError:
                            pass
                        logger.info('session %d closed', sid)
            else:
                time.sleep(0.001)

    def _target_pipe(tun, conn, sid, q, lock):
        try:
            pipe(tun, conn, sid, q)
        finally:
            with lock:
                sessions.pop(sid, None)
            logger.info('session %d disconnected', sid)

    threading.Thread(target=dispatcher, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


# ── main ─────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description='Serial TCP Tunnel')
    p.add_argument('phy', help='COM3, COM3:9600, tcp:host:port')
    p.add_argument('-l', '--listen', type=int, metavar='PORT', help='listen TCP, bridge to serial')
    p.add_argument('-t', '--target', metavar='HOST:PORT', help='connect serial to TCP target')
    p.add_argument('--log', default='INFO')
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper()),
        format='%(asctime)s [%(levelname)s] %(message)s',
    )

    phy = parse_phy(args.phy)
    tun = Tunnel(phy)
    tun.open()
    logger.info('tunnel %s', phy.name)

    try:
        if args.target:
            run_target(tun, args.target)
        else:
            run_listen(tun, args.listen or 9000)
    except KeyboardInterrupt:
        pass
    finally:
        tun.close()


if __name__ == '__main__':
    main()
