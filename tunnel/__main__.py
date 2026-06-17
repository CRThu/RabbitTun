import argparse
import logging
import socket
import threading

from .phy.serial_phy import SerialPhy
from .phy.tcp_phy import TcpPhy
from .tunnel import Tunnel

logger = logging.getLogger(__name__)


def _parse_phy(spec: str) -> tuple:
    """Parse physical layer spec.
    COM3               → (SerialPhy, 'COM3', 115200)
    COM3:9600          → (SerialPhy, 'COM3', 9600)
    tcp:1.2.3.4:9000   → (TcpPhy, '1.2.3.4', 9000)
    """
    if spec.startswith('tcp:'):
        rest = spec[4:]
        host, port = rest.rsplit(':', 1)
        return (TcpPhy, host, int(port))
    if ':' in spec:
        port, baud = spec.rsplit(':', 1)
        return (SerialPhy, port, int(baud))
    return (SerialPhy, spec, 115200)


def run_tcp_bridge(tun: Tunnel, host: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(5)
    sock.settimeout(1.0)
    logger.info('TCP bridge on %s:%d', host, port)

    try:
        while True:
            try:
                conn, addr = sock.accept()
                logger.info('client connected: %s', addr)
                threading.Thread(target=_tcp_bridge_client, args=(tun, conn), daemon=True).start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


def _tcp_bridge_client(tun: Tunnel, conn: socket.socket) -> None:
    conn.settimeout(3.0)
    stop = threading.Event()

    def to_phy():
        while not stop.is_set():
            try:
                data = conn.recv(65536)
                if not data:
                    break
                tun.send(data)
            except socket.timeout:
                continue
            except OSError:
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
                    stop.set()
                    return

    threads = [threading.Thread(target=t, daemon=True) for t in (to_phy, from_phy)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    conn.close()


def run_udp_bridge(tun: Tunnel, host: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.settimeout(1.0)
    logger.info('UDP bridge on %s:%d', host, port)

    peers: set[tuple] = set()
    stop = threading.Event()

    def drain():
        while not stop.is_set():
            data = tun.recv(timeout=0.05)
            if data:
                for peer in list(peers):
                    try:
                        sock.sendto(data, peer)
                    except OSError:
                        pass

    threading.Thread(target=drain, daemon=True).start()

    try:
        while True:
            try:
                data, addr = sock.recvfrom(65536)
                peers.add(addr)
                tun.send(data)
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Serial Tunnel')
    parser.add_argument('phy', help='physical layer: COM3, COM3:9600, tcp:host:port')
    parser.add_argument('--mode', choices=['tcp', 'udp', 'proxy', 'relay'], default='tcp', help='bridge mode')
    parser.add_argument('--listen', type=int, default=None)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--log', default='INFO')
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper()),
        format='%(asctime)s [%(levelname)s] %(message)s',
    )

    cls, *params = _parse_phy(args.phy)
    phy = cls(*params)
    tun = Tunnel(phy)
    tun.open()
    logger.info('tunnel up  %s  (%s)', phy.name, args.mode)

    try:
        if args.mode == 'tcp':
            run_tcp_bridge(tun, args.host, args.listen or 9000)
        elif args.mode == 'udp':
            run_udp_bridge(tun, args.host, args.listen or 9000)
        elif args.mode == 'proxy':
            from .proxy import Mux, ProxyServer
            mux = Mux(tun)
            mux.start()
            port = args.listen or 1080
            ProxyServer(mux, args.host, port).serve()
        elif args.mode == 'relay':
            from .proxy import Mux, RelayServer
            mux = Mux(tun)
            mux.start()
            RelayServer(mux)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            mux.stop()
    except KeyboardInterrupt:
        pass
    finally:
        tun.close()


if __name__ == '__main__':
    main()
