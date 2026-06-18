"""
RabbitTun 串口波特率测试

用法:
  python test_max_baud.py              测试所有波特率
  python test_max_baud.py 115200 460800  测试指定波特率
"""
import sys
import time
import struct
import threading
import socket
import os
import hashlib

sys.path.insert(0, os.path.dirname(__file__))

COM_A = 'COM3'
COM_B = 'COM18'
SEND_KB = 50


def find_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _echo(conn):
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            conn.sendall(data)
    except OSError:
        pass
    conn.close()


def echo_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(5)
    srv.settimeout(15)
    while True:
        try:
            conn, _ = srv.accept()
            threading.Thread(target=_echo, args=(conn,), daemon=True).start()
        except socket.timeout:
            break
    srv.close()


def test_baud(baudrate):
    from tunnel.phy import SerialPhy
    from tunnel.tunnel import Tunnel
    from tunnel.cli import run_listen, run_target

    echo_port = find_free_port()
    tunnel_port = find_free_port()

    threading.Thread(target=echo_server, args=(echo_port,), daemon=True).start()

    phy_a = SerialPhy(COM_A, baudrate)
    tun_a = Tunnel(phy_a)
    tun_a.open()
    threading.Thread(target=run_target, args=(tun_a, f'127.0.0.1:{echo_port}'), daemon=True).start()

    phy_b = SerialPhy(COM_B, baudrate)
    tun_b = Tunnel(phy_b)
    tun_b.open()
    threading.Thread(target=run_listen, args=(tun_b, tunnel_port), daemon=True).start()

    time.sleep(1.5)

    # -- single session throughput --
    try:
        sock = socket.create_connection(('127.0.0.1', tunnel_port), timeout=5)
    except Exception:
        tun_a.close()
        tun_b.close()
        return {'baudrate': baudrate, 'error': 'connect failed'}

    total = SEND_KB * 1024
    sent = 0
    recv_buf = b''
    md5_send = hashlib.md5()

    t0 = time.perf_counter()
    while sent < total:
        pkt = os.urandom(1024)
        md5_send.update(pkt)
        try:
            sock.sendall(pkt)
            sent += 1024
        except Exception:
            break

    deadline = t0 + 10
    while len(recv_buf) < sent and time.perf_counter() < deadline:
        try:
            data = sock.recv(min(65536, sent - len(recv_buf)))
            if not data:
                break
            recv_buf += data
        except (socket.timeout, OSError):
            break

    elapsed = time.perf_counter() - t0
    sock.close()

    integrity = hashlib.md5(recv_buf).hexdigest() == md5_send.hexdigest() if recv_buf else False
    speed = len(recv_buf) / elapsed / 1024 if elapsed > 0 else 0
    theoretical = baudrate / 10 / 1024
    loss_rate = (1 - len(recv_buf) / sent) * 100 if sent > 0 else 0

    # -- latency (5 rounds) --
    time.sleep(3)
    latencies = []
    for i in range(5):
        try:
            s2 = socket.create_connection(('127.0.0.1', tunnel_port), timeout=5)
            ts = time.perf_counter()
            s2.sendall(struct.pack('!d', ts))
            s2.settimeout(3)
            r = b''
            while len(r) < 8:
                c = s2.recv(8 - len(r))
                if not c:
                    break
                r += c
            if len(r) == 8:
                latencies.append((time.perf_counter() - ts) * 1000)
            s2.close()
        except Exception as e:
            latencies.append(-999)
        time.sleep(0.3)

    latencies = [l for l in latencies if l > 0]
    lat_avg = sum(latencies) / len(latencies) if latencies else 0

    # -- concurrent 2 sessions --
    time.sleep(0.5)
    results = [None, None]
    barrier = threading.Barrier(2)

    def worker(idx):
        try:
            barrier.wait()
            s = socket.create_connection(('127.0.0.1', tunnel_port), timeout=5)
            pkt = bytes([idx]) * 1024
            target = (SEND_KB // 2) * 1024
            sent = 0
            recv_buf = b''
            t0 = time.perf_counter()
            while sent < target:
                s.sendall(pkt)
                sent += 1024
            deadline = t0 + 10
            while len(recv_buf) < sent and time.perf_counter() < deadline:
                c = s.recv(min(65536, sent - len(recv_buf)))
                if not c:
                    break
                recv_buf += c
            elapsed = time.perf_counter() - t0
            ok = len(recv_buf) == sent and all(b == idx for b in recv_buf)
            results[idx] = (len(recv_buf) / elapsed / 1024, ok)
            s.close()
        except Exception as e:
            results[idx] = (0, str(e))

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    tun_a.close()
    tun_b.close()

    return {
        'baudrate': baudrate,
        'theoretical': theoretical,
        'single_kbs': speed,
        'single_integrity': integrity,
        'latency_avg_ms': lat_avg,
        'loss_rate': loss_rate,
        'concurrent': results,
    }


def main():
    import struct  # noqa: F401 — needed by test_baud

    baudrates = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [
        115200, 230400, 460800, 921600, 1000000, 2000000,
    ]

    from tunnel.frame import MAX_PAYLOAD

    print('=' * 60)
    print(f'RabbitTun Baud Rate Test')
    print(f'  {COM_A} <-> {COM_B}  MAX_PAYLOAD={MAX_PAYLOAD}  {SEND_KB}KB')
    print('=' * 60)
    print(f'{"Baud":>10} {"Theory":>8} {"Single":>8} {"Eff%":>6} {"Lat":>8} {"Loss%":>7} {"Concur":>8} {"Integ":>6}')
    print('-' * 67)

    for baud in baudrates:
        try:
            r = test_baud(baud)
        except Exception as e:
            print(f'{baud:>10}  ERROR: {e}')
            continue

        if 'error' in r:
            print(f'{r["baudrate"]:>10}  {r["error"]}')
            continue

        th = r['theoretical']
        sp = r['single_kbs']
        eff = sp / th * 100 if th > 0 else 0
        c_ok = all(
            c[1] for c in r['concurrent']
            if c and not isinstance(c[1], str)
        )
        c_tot = sum(
            c[0] for c in r['concurrent']
            if c and not isinstance(c[1], str)
        )
        ok = 'ok' if r['single_integrity'] and c_ok else 'FAIL'

        loss = r.get('loss_rate', -1)
        loss_s = f'{loss:.1f}' if loss >= 0 else 'N/A'
        print(
            f'{r["baudrate"]:>10} {th:>7.1f} {sp:>7.1f} {eff:>5.0f}% '
            f'{r["latency_avg_ms"]:>7.1f} {loss_s:>6} {c_tot:>7.1f} {ok:>6}'
        )

    print('=' * 60)


if __name__ == '__main__':
    main()
