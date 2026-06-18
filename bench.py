"""
RabbitTun 性能测试

用法:
  python bench.py loop       TCP 回环基线（无隧道）
  python bench.py tunnel     串口隧道测试
  python bench.py frame      帧协议编解码开销
"""
import socket
import time
import struct
import threading
import sys
import os
import hashlib
import random

sys.path.insert(0, os.path.dirname(__file__))

# ── helpers ──────────────────────────────────────────────

def find_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def echo_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(5)
    srv.settimeout(30)
    while True:
        try:
            conn, _ = srv.accept()
            threading.Thread(target=_echo, args=(conn,), daemon=True).start()
        except socket.timeout:
            break
    srv.close()


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


# ── benchmark functions ──────────────────────────────────

def bench_throughput_tcp(addr, total_kb=200):
    """TCP 回环吞吐量 — 定量发送，测量端到端回送时间"""
    sock = socket.create_connection(addr, timeout=5)
    total = total_kb * 1024
    chunk = 1024
    sent = 0
    recv_buf = b''
    md5_send = hashlib.md5()

    t0 = time.perf_counter()
    while sent < total:
        pkt = os.urandom(chunk)
        md5_send.update(pkt)
        sock.sendall(pkt)
        sent += chunk

    while len(recv_buf) < sent:
        try:
            data = sock.recv(min(65536, sent - len(recv_buf)))
            if not data:
                break
            recv_buf += data
        except (socket.timeout, OSError):
            break

    elapsed = time.perf_counter() - t0
    sock.close()

    md5_recv = hashlib.md5(recv_buf).hexdigest() if recv_buf else ''
    return {
        'sent_kb': sent / 1024,
        'recv_kb': len(recv_buf) / 1024,
        'elapsed': elapsed,
        'speed': len(recv_buf) / elapsed / 1024,
        'integrity': md5_send.hexdigest() == md5_recv,
    }


def bench_throughput_tunnel(addr, total_kb=100):
    """串口隧道吞吐量 — 定量发送，测量实际端到端时间"""
    sock = socket.create_connection(addr, timeout=10)
    total = total_kb * 1024
    chunk = 1024
    sent = 0
    recv_buf = b''
    md5_send = hashlib.md5()

    # 发送阶段
    t0 = time.perf_counter()
    while sent < total:
        pkt = os.urandom(chunk)
        md5_send.update(pkt)
        sock.sendall(pkt)
        sent += chunk

    # 等待回送完成
    while len(recv_buf) < sent:
        try:
            data = sock.recv(min(65536, sent - len(recv_buf)))
            if not data:
                break
            recv_buf += data
        except (socket.timeout, OSError):
            break

    elapsed = time.perf_counter() - t0
    sock.close()

    md5_recv = hashlib.md5(recv_buf).hexdigest() if recv_buf else ''
    return {
        'sent_kb': sent / 1024,
        'recv_kb': len(recv_buf) / 1024,
        'elapsed': elapsed,
        'speed': len(recv_buf) / elapsed / 1024,
        'integrity': md5_send.hexdigest() == md5_recv,
    }


def bench_latency(addr, count=50):
    """延迟测试 — 8 字节 roundtrip，串行发收"""
    sock = socket.create_connection(addr, timeout=5)
    times = []
    for _ in range(count):
        ts = time.perf_counter()
        payload = struct.pack('!d', ts)
        try:
            sock.sendall(payload)
        except OSError:
            break
        sock.settimeout(5)
        recv = b''
        try:
            while len(recv) < 8:
                chunk = sock.recv(8 - len(recv))
                if not chunk:
                    break
                recv += chunk
        except (socket.timeout, OSError):
            continue
        if len(recv) == 8:
            rtt = (time.perf_counter() - ts) * 1000
            times.append(rtt)
        time.sleep(0.05)
    sock.close()
    if not times:
        return None
    times.sort()
    return {
        'avg': sum(times) / len(times),
        'p50': times[len(times) // 2],
        'p99': times[int(len(times) * 0.99)],
        'min': times[0],
        'max': times[-1],
        'n': len(times),
    }


def bench_integrity(addr, rounds=30):
    """完整性测试 — 随机大小随机数据，逐字节校验"""
    sock = socket.create_connection(addr, timeout=5)
    errors = 0
    total = 0
    for _ in range(rounds):
        size = random.randint(1, 4096)
        payload = bytes(random.getrandbits(8) for _ in range(size))
        try:
            sock.sendall(struct.pack('!I', size) + payload)
        except OSError:
            break
        sock.settimeout(5)
        recv = b''
        try:
            while len(recv) < 4 + size:
                chunk = sock.recv(min(4096, 4 + size - len(recv)))
                if not chunk:
                    break
                recv += chunk
        except (socket.timeout, OSError):
            errors += 1
            continue
        total += size
        if len(recv) != 4 + size:
            errors += 1
            continue
        r_size, r_payload = struct.unpack('!I', recv[:4]), recv[4:]
        if r_size[0] != size or r_payload != payload:
            errors += 1
    sock.close()
    return {'rounds': rounds, 'total_kb': total / 1024, 'errors': errors}


def bench_loss(addr, count=50):
    """丢包测试 — 发送 N 个序号包，统计回送率"""
    sock = socket.create_connection(addr, timeout=5)
    sent_ids = set()
    for i in range(count):
        sock.sendall(struct.pack('!I', i))
        sent_ids.add(i)
    received = set()
    while True:
        try:
            sock.settimeout(3)
            data = sock.recv(4)
            if not data:
                break
            seq = struct.unpack('!I', data)[0]
            received.add(seq)
        except socket.timeout:
            break
    sock.close()
    lost = sent_ids - received
    loss_rate = len(lost) / count * 100
    return {'sent': count, 'received': len(received), 'lost': len(lost), 'rate': loss_rate}


# ── test modes ───────────────────────────────────────────

def test_loop():
    port = find_free_port()
    t = threading.Thread(target=echo_server, args=(port,), daemon=True)
    t.start()
    time.sleep(0.3)
    addr = ('127.0.0.1', port)

    print('=== TCP Loopback (baseline) ===')
    r = bench_throughput_tcp(addr)
    print(f"  throughput: {r['speed']:.1f}KB/s sent={r['sent_kb']:.0f}KB recv={r['recv_kb']:.0f}KB integrity={'ok' if r['integrity'] else 'FAIL'}")
    r = bench_latency(addr)
    if r:
        print(f"  latency:    avg={r['avg']:.2f}ms p50={r['p50']:.2f}ms p99={r['p99']:.2f}ms")
    r = bench_integrity(addr)
    print(f"  integrity:  {r['total_kb']:.0f}KB {r['errors']} errors")


def test_tunnel():
    from tunnel.phy import SerialPhy
    from tunnel.tunnel import Tunnel
    from tunnel.cli import pipe

    echo_port = find_free_port()
    tunnel_listen = find_free_port()

    # echo server
    threading.Thread(target=echo_server, args=(echo_port,), daemon=True).start()

    # COM3 -> echo (target) with session lock
    phy3 = SerialPhy('COM3')
    tun3 = Tunnel(phy3)
    tun3.open()

    com3_lock = threading.Lock()

    def com3_loop():
        while True:
            if not com3_lock.acquire(blocking=True):
                time.sleep(0.1)
                continue
            try:
                conn = socket.create_connection(('127.0.0.1', echo_port), timeout=5)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                pipe(tun3, conn)
            except (ConnectionRefusedError, OSError):
                time.sleep(2)
            finally:
                com3_lock.release()

    threading.Thread(target=com3_loop, daemon=True).start()

    # COM18 listen with session lock
    phy18 = SerialPhy('COM18')
    tun18 = Tunnel(phy18)
    tun18.open()

    listen_lock = threading.Lock()

    def com18_listen():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', tunnel_listen))
        srv.listen(5)
        srv.settimeout(1.0)
        while True:
            try:
                conn, _ = srv.accept()
                if not listen_lock.acquire(blocking=False):
                    conn.close()
                    continue
                threading.Thread(target=_session_pipe, args=(tun18, conn, listen_lock), daemon=True).start()
            except socket.timeout:
                continue

    def _session_pipe(tun, conn, lock):
        try:
            pipe(tun, conn)
        finally:
            lock.release()

    threading.Thread(target=com18_listen, daemon=True).start()
    time.sleep(2)

    print('=== Serial Tunnel (COM3 <-> COM18) ===')

    # throughput
    addr = ('127.0.0.1', tunnel_listen)
    r = bench_throughput_tunnel(addr, total_kb=50)
    print(f"  throughput: {r['speed']:.1f}KB/s sent={r['sent_kb']:.0f}KB recv={r['recv_kb']:.0f}KB integrity={'ok' if r['integrity'] else 'FAIL'}")

    # 等待串口积压清空
    print('  waiting for serial backlog to clear...')
    time.sleep(5)

    # latency - 新连接
    addr2 = ('127.0.0.1', tunnel_listen)
    r = bench_latency(addr2, count=20)
    if r:
        print(f"  latency:    avg={r['avg']:.2f}ms p50={r['p50']:.2f}ms p99={r['p99']:.2f}ms n={r['n']}")

    # integrity - 新连接
    time.sleep(1)
    addr3 = ('127.0.0.1', tunnel_listen)
    r = bench_integrity(addr3, rounds=20)
    print(f"  integrity:  {r['total_kb']:.0f}KB {r['errors']} errors")

    # loss - 新连接
    time.sleep(1)
    addr4 = ('127.0.0.1', tunnel_listen)
    r = bench_loss(addr4, count=50)
    print(f"  loss:       sent={r['sent']} recv={r['received']} lost={r['lost']} rate={r['rate']:.1f}%")

    tun3.close()
    tun18.close()


def test_frame():
    from tunnel.frame import encode, Decoder

    print('=== Frame encode/decode ===')
    payload = bytes(1024)
    N = 10000

    start = time.perf_counter()
    for _ in range(N):
        encode(payload)
    t_enc = time.perf_counter() - start
    print(f"  encode:    {N/t_enc:.0f} frames/s ({N*1024/t_enc/1024/1024:.1f} MB/s)")

    encoded = encode(payload)
    dec = Decoder()
    start = time.perf_counter()
    for _ in range(N):
        dec.feed(encoded)
    t_dec = time.perf_counter() - start
    print(f"  decode:    {N/t_dec:.0f} frames/s ({N*1024/t_dec/1024/1024:.1f} MB/s)")

    # integrity
    dec2 = Decoder()
    errors = 0
    for i in range(1000):
        size = random.randint(1, 4096)
        data = bytes(random.getrandbits(8) for _ in range(size))
        frames = dec2.feed(encode(data))
        if not frames or frames[0] != data:
            errors += 1
    print(f"  integrity: 1000 random frames, {errors} errors")


# ── main ─────────────────────────────────────────────────

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'loop':
        test_loop()
    elif mode == 'tunnel':
        test_tunnel()
    elif mode == 'frame':
        test_frame()
    else:
        print('usage: python bench.py [loop|tunnel|frame]')
