import argparse
import logging
import socket
import threading
import time

from .phy import SerialPhy, TcpPhy
from .tunnel import Tunnel

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


def pipe(tun: Tunnel, conn: socket.socket) -> None:
    stop = threading.Event()

    def to_phy():
        while not stop.is_set():
            try:
                data = conn.recv(65536)
                if not data:
                    break
                tun.send(data)
            except (socket.timeout, OSError):
                break
        stop.set()

    def from_phy():
        while not stop.is_set():
            data = tun.recv(timeout=0.05)
            if data is None:
                continue
            if data:
                try:
                    conn.sendall(data)
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


def main() -> None:
    p = argparse.ArgumentParser(description='Serial TCP Tunnel')
    p.add_argument('phy', help='COM3, COM3:9600, tcp:host:port')
    p.add_argument('-l', '--listen', type=int, metavar='PORT', help='listen TCP, bridge to serial')
    p.add_argument('-t', '--target', metavar='HOST:PORT', help='connect serial to target')
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
