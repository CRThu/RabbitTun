import argparse
import logging
import socket
import threading
import time

from .phy import SerialPhy, TcpPhy
from .tunnel import Tunnel, MuxTunnel
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


# ── single session pipe ──────────────────────────────────

def pipe(tun: Tunnel, conn: socket.socket, sid: int = 0) -> None:
    stop = threading.Event()

    def to_phy():
        while not stop.is_set():
            try:
                data = conn.recv(65536)
                if not data:
                    break
                tun.send(data, sid)
            except (socket.timeout, OSError):
                break
        stop.set()

    def from_phy():
        while not stop.is_set():
            frame = tun.recv(timeout=0.05)
            if frame is None:
                continue
            ftype, fsid, fdata = frame
            if ftype == TYPE_DATA and fsid == sid and fdata:
                try:
                    conn.sendall(fdata)
                except OSError:
                    break
        stop.set()

    t1 = threading.Thread(target=to_phy, daemon=True)
    t2 = threading.Thread(target=from_phy, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    conn.close()


# ── mux pipe ─────────────────────────────────────────────

def pipe_mux(mux: MuxTunnel, conn: socket.socket, sid: int) -> None:
    q = mux.register(sid)
    stop = threading.Event()

    def to_phy():
        while not stop.is_set():
            try:
                data = conn.recv(65536)
                if not data:
                    break
                mux.send(sid, data)
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
    mux.unregister(sid)
    conn.close()


# ── single session listen/target ─────────────────────────

def run_listen(tun: Tunnel, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(5)
    srv.settimeout(1.0)
    logger.info('listen :%d', port)
    session_lock = threading.Lock()

    try:
        while True:
            try:
                conn, addr = srv.accept()
                if not session_lock.acquire(blocking=False):
                    logger.info('reject %s (busy)', addr)
                    conn.close()
                    continue
                logger.info('peer %s', addr)
                threading.Thread(target=_session_pipe, args=(tun, conn, session_lock), daemon=True).start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


def _session_pipe(tun: Tunnel, conn: socket.socket, lock: threading.Lock) -> None:
    try:
        pipe(tun, conn)
    finally:
        lock.release()


def run_target(tun: Tunnel, target: str) -> None:
    host, port = target.rsplit(':', 1)
    logger.info('target %s:%s', host, port)
    while True:
        try:
            conn = socket.create_connection((host, int(port)), timeout=5)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            logger.info('connected')
            pipe(tun, conn)
            logger.info('disconnected, retrying in 1s')
            time.sleep(1)
        except (ConnectionRefusedError, OSError) as e:
            logger.warning('unreachable: %s', e)
            time.sleep(2)
        except KeyboardInterrupt:
            break


# ── multiplexed listen/target ────────────────────────────

def run_mux_listen(mux: MuxTunnel, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(5)
    srv.settimeout(1.0)
    logger.info('mux listen :%d', port)

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
                mux.send_frame(TYPE_OPEN, sid)
                threading.Thread(target=_mux_pipe, args=(mux, conn, sid, sessions, lock), daemon=True).start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


def _mux_pipe(mux: MuxTunnel, conn: socket.socket, sid: int, sessions: dict, lock: threading.Lock) -> None:
    try:
        pipe_mux(mux, conn, sid)
    finally:
        with lock:
            sessions.pop(sid, None)
        mux.send_frame(TYPE_CLOSE, sid)
        logger.info('session %d disconnected', sid)


def run_mux_target(mux: MuxTunnel, target: str) -> None:
    host, port = target.rsplit(':', 1)
    logger.info('mux target %s:%s', host, port)

    sessions: dict[int, socket.socket] = {}
    lock = threading.Lock()

    def dispatcher():
        while True:
            if mux._all_q:
                ftype, sid, fdata = mux._all_q.popleft()
                if ftype == TYPE_OPEN:
                    try:
                        conn = socket.create_connection((host, int(port)), timeout=5)
                        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        with lock:
                            sessions[sid] = conn
                        logger.info('session %d connected to %s:%s', sid, host, port)
                        threading.Thread(target=_mux_target_pipe, args=(mux, conn, sid, lock), daemon=True).start()
                    except (ConnectionRefusedError, OSError) as e:
                        logger.warning('session %d connect failed: %s', sid, e)
                        mux.send_frame(TYPE_CLOSE, sid)
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

    def _mux_target_pipe(mux, conn, sid, lock):
        try:
            pipe_mux(mux, conn, sid)
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
    p.add_argument('-l', '--listen', type=int, metavar='PORT', help='listen TCP, bridge to serial (single session)')
    p.add_argument('-t', '--target', metavar='HOST:PORT', help='connect serial to TCP target (single session)')
    p.add_argument('-L', '--mux-listen', type=int, metavar='PORT', help='listen TCP, multiplexed bridge to serial')
    p.add_argument('-T', '--mux-target', metavar='HOST:PORT', help='connect serial to TCP target (multiplexed)')
    p.add_argument('--log', default='INFO')
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper()),
        format='%(asctime)s [%(levelname)s] %(message)s',
    )

    phy = parse_phy(args.phy)
    logger.info('tunnel %s', phy.name)

    if args.mux_target or args.mux_listen:
        mux = MuxTunnel(phy)
        mux.open()
        try:
            if args.mux_target:
                run_mux_target(mux, args.mux_target)
            else:
                run_mux_listen(mux, args.mux_listen or 9000)
        except KeyboardInterrupt:
            pass
        finally:
            mux.close()
    else:
        tun = Tunnel(phy)
        tun.open()
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
