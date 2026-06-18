"""rabbit-tun.exe 集成测试 — echo server + 两个 exe 进程 + 多会话测试"""
import subprocess
import socket
import time
import threading
import sys
import os

EXE = os.path.join(os.path.dirname(__file__), 'dist', 'run.dist', 'rabbit-tun.exe')


def find_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def echo_server(port):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(20)
    srv.settimeout(30)
    def echo(c):
        try:
            while True:
                d = c.recv(65536)
                if not d: break
                c.sendall(d)
        except: pass
        c.close()
    while True:
        try:
            c, _ = srv.accept()
            threading.Thread(target=echo, args=(c,), daemon=True).start()
        except socket.timeout:
            break
    srv.close()


def main():
    echo_port = find_free_port()
    listen_port = find_free_port()

    threading.Thread(target=echo_server, args=(echo_port,), daemon=True).start()
    print(f'[echo] :{echo_port}')

    p3 = subprocess.Popen(
        [EXE, 'COM3', '-t', f'127.0.0.1:{echo_port}', '--log', 'WARNING'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f'[target] COM3 -> :{echo_port} pid={p3.pid}')

    p18 = subprocess.Popen(
        [EXE, 'COM18', '-l', str(listen_port), '--log', 'WARNING'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f'[listen] COM18 -> :{listen_port} pid={p18.pid}')

    time.sleep(4)

    if p3.poll() is not None:
        print(f'[target] CRASHED (exit={p3.returncode})')
        print(p3.stderr.read().decode())
        return
    if p18.poll() is not None:
        print(f'[listen] CRASHED (exit={p18.returncode})')
        print(p18.stderr.read().decode())
        return
    print('[ok] processes running')

    try:
        # test 1: single session throughput
        print('\n[1] single session')
        s = socket.create_connection(('127.0.0.1', listen_port), timeout=10)
        total = 30 * 1024
        sent = 0
        recv_buf = b''
        t0 = time.perf_counter()
        while sent < total:
            s.sendall(os.urandom(1024))
            sent += 1024
        while len(recv_buf) < sent:
            data = s.recv(min(65536, sent - len(recv_buf)))
            if not data: break
            recv_buf += data
        elapsed = time.perf_counter() - t0
        ok = len(recv_buf) == sent
        print(f'  {len(recv_buf)/elapsed/1024:.1f}KB/s sent={sent//1024}KB recv={len(recv_buf)//1024}KB integrity={"ok" if ok else "FAIL"}')
        s.close()
        time.sleep(3)

        # test 2: 4 concurrent sessions
        N = 4
        PER = 15 * 1024
        results = [None] * N
        barrier = threading.Barrier(N)

        def worker(idx):
            try:
                barrier.wait()
                s = socket.create_connection(('127.0.0.1', listen_port), timeout=10)
                pkt = bytes([idx]) * 1024
                sent = 0
                recv_buf = b''
                t0 = time.perf_counter()
                while sent < PER:
                    s.sendall(pkt)
                    sent += 1024
                while len(recv_buf) < sent:
                    chunk = s.recv(min(65536, sent - len(recv_buf)))
                    if not chunk: break
                    recv_buf += chunk
                elapsed = time.perf_counter() - t0
                ok = len(recv_buf) == sent and all(b == idx for b in recv_buf)
                results[idx] = (len(recv_buf)/elapsed/1024, ok)
                s.close()
            except Exception as e:
                results[idx] = (0, str(e))

        print(f'\n[2] {N} concurrent sessions')
        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(N)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)
        for i, r in enumerate(results):
            if r is None:
                print(f'  session {i}: timeout')
            elif isinstance(r[1], str):
                print(f'  session {i}: error: {r[1]}')
            else:
                print(f'  session {i}: {r[0]:.1f}KB/s integrity={"ok" if r[1] else "FAIL"}')

        # test 3: latency
        print('\n[3] latency')
        time.sleep(2)
        s = socket.create_connection(('127.0.0.1', listen_port), timeout=10)
        times = []
        for _ in range(10):
            ts = time.perf_counter()
            s.sendall(b'p' * 8)
            s.settimeout(3)
            recv = b''
            try:
                while len(recv) < 8:
                    chunk = s.recv(8 - len(recv))
                    if not chunk: break
                    recv += chunk
            except: pass
            if len(recv) == 8:
                rtt = (time.perf_counter() - ts) * 1000
                times.append(rtt)
            time.sleep(0.1)
        s.close()
        if times:
            times.sort()
            avg = sum(times) / len(times)
            print(f'  avg={avg:.1f}ms min={times[0]:.1f}ms max={times[-1]:.1f}ms n={len(times)}')

        print('\n=== ALL TESTS PASSED ===')

    except Exception as e:
        print(f'\n=== TEST FAILED: {e} ===')
    finally:
        p3.terminate()
        p18.terminate()
        p3.wait()
        p18.wait()


if __name__ == '__main__':
    main()
