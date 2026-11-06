"""Run offline tests with a loopback-only socket guard in the test process."""
import contextlib
import ipaddress
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def is_local(host):
    if isinstance(host, bytes):
        host = host.decode('ascii', errors='replace')
    if host == 'localhost':
        return True
    if not isinstance(host, str):
        return False
    try:
        return ipaddress.ip_address(host.split('%', 1)[0]).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def loopback_only():
    real_resolve = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto

    def resolve(host, *args, **kwargs):
        if host is not None and not is_local(host):
            raise PermissionError('Offline test runner blocked external name resolution')
        return real_resolve(host, *args, **kwargs)

    def allowed(sock, address):
        return sock.family == socket.AF_UNIX or (isinstance(address, tuple) and address and is_local(address[0]))

    def connect(sock, address):
        if not allowed(sock, address):
            raise PermissionError('Offline test runner blocked external connection')
        return real_connect(sock, address)

    def connect_ex(sock, address):
        if not allowed(sock, address):
            raise PermissionError('Offline test runner blocked external connection')
        return real_connect_ex(sock, address)

    def sendto(sock, data, *args):
        if not args or not allowed(sock, args[-1]):
            raise PermissionError('Offline test runner blocked external datagram')
        return real_sendto(sock, data, *args)

    with patch.object(socket, 'getaddrinfo', resolve), patch.object(socket.socket, 'connect', connect), \
         patch.object(socket.socket, 'connect_ex', connect_ex), patch.object(socket.socket, 'sendto', sendto):
        yield


def main():
    with loopback_only():
        if sys.argv[1:] == ['--probe']:
            def blocked(fn):
                try: fn()
                except PermissionError: return
                raise RuntimeError('External network operation unexpectedly allowed')
            blocked(lambda: socket.create_connection(('example.invalid', 443), timeout=1))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
                blocked(lambda: stream.connect(('192.0.2.1', 443)))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
                blocked(lambda: datagram.sendto(b'test', ('192.0.2.1', 53)))
            if not socket.getaddrinfo('localhost', 80): raise RuntimeError('Loopback resolution failed')
            print('external access blocked')
            return 0
        if sys.argv[1:]:
            raise SystemExit('Usage: python scripts/offline_tests.py [--probe]')
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
