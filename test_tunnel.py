"""End-to-end tunnel test.
Connects to both tunnel endpoints and verifies data passes through.
"""

import socket
import threading
import time


def test_roundtrip():
    s3 = socket.create_connection(('127.0.0.1', 9000), timeout=5)
    s4 = socket.create_connection(('127.0.0.1', 9001), timeout=5)

    received = []

    def recv_loop(sock, store):
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                store.append(data)
        except OSError:
            pass

    t = threading.Thread(target=recv_loop, args=(s4, received), daemon=True)
    t.start()

    payload = b'Hello RabbitTun!'
    s3.send(payload)
    time.sleep(2)

    s3.close()
    s4.close()

    if received and received[0] == payload:
        print(f'OK: received expected payload ({len(payload)} bytes)')
    else:
        print(f'FAIL: expected {payload!r}, got {received!r}')


if __name__ == '__main__':
    print('Make sure both tunnel instances are running:')
    print('  run_tunnel_a.bat  (COM3 -> :9000)')
    print('  run_tunnel_b.bat  (COM4 -> :9001)')
    print()
    test_roundtrip()
