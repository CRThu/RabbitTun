import argparse
import logging
import socket
import threading
import time

logger = logging.getLogger(__name__)


def run_bridge(port_a: int, port_b: int, host: str = "127.0.0.1") -> None:
    """Connect two local TCP services together persistently."""
    _ensure_port(host, port_a)
    _ensure_port(host, port_b)

    logger.info("Bridge: connecting %s:%d  %s:%d", host, port_a, host, port_b)

    while True:
        try:
            a = socket.create_connection((host, port_a), timeout=5)
            b = socket.create_connection((host, port_b), timeout=5)
            _bridge_sockets(a, b)
        except (ConnectionRefusedError, OSError) as e:
            logger.warning("Bridge retry: %s", e)
            time.sleep(2)


def _ensure_port(host: str, port: int) -> None:
    """Quick check that something is listening on host:port."""
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((host, port))
        s.close()
    except (ConnectionRefusedError, OSError):
        logger.info("Waiting for %s:%d to become available...", host, port)


def _bridge_sockets(a: socket.socket, b: socket.socket) -> None:
    stop = threading.Event()

    def fwd(src: socket.socket, dst: socket.socket) -> None:
        while not stop.is_set():
            try:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
            except OSError:
                break
        stop.set()

    threading.Thread(target=fwd, args=(a, b), daemon=True).start()
    threading.Thread(target=fwd, args=(b, a), daemon=True).start()

    try:
        while not stop.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent TCP bridge")
    parser.add_argument("port_a", type=int, help="first port")
    parser.add_argument("port_b", type=int, help="second port")
    parser.add_argument("--host", default="127.0.0.1", help="host (default 127.0.0.1)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    run_bridge(args.port_a, args.port_b, args.host)


if __name__ == "__main__":
    main()
