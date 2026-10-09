"""Unprivileged client for the narrowly scoped NetworkManager helper."""
import json
import socket


def request(value):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(4)
        client.connect('/run/djtable-network/control.sock')
        client.sendall(json.dumps(value).encode()+b'\n')
        with client.makefile('rb') as stream:
            result = json.loads(stream.readline(8192))
    if 'error' in result and value.get('action') != 'status':
        raise ValueError(result['error'])
    return result
