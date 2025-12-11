# pipeline_cancel.py
from threading import Lock

_CANCEL_FLAG = False
_LOCK = Lock()

def request_cancel():
    global _CANCEL_FLAG
    with _LOCK:
        _CANCEL_FLAG = True

def reset_cancel():
    global _CANCEL_FLAG
    with _LOCK:
        _CANCEL_FLAG = False

def should_cancel() -> bool:
    with _LOCK:
        return _CANCEL_FLAG
