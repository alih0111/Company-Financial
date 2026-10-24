import socket
def _blocked(*a, **k): raise RuntimeError('NETWORK_BLOCKED_BY_TF03_HARNESS')
socket.socket.connect=_blocked
socket.create_connection=_blocked
