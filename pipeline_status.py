# pipeline_status.py
import json
from pathlib import Path
from threading import Lock

STATUS_FILE = Path("pipeline_status.json")
_LOCK = Lock()


def _load_status():
    if not STATUS_FILE.exists():
        return {}
    try:
        with STATUS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Si se corrompe, empezamos limpio
        return {}


def _save_status(status: dict):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_FILE.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=4)


def mark_stage_done(libro: str, capitulo: int, stage: str):
    """
    stage ∈ {"json", "tts", "imagenes", "full"} por ejemplo.
    """
    with _LOCK:
        status = _load_status()
        libro_key = libro.lower()
        book_status = status.setdefault(libro_key, {})
        caps = book_status.setdefault(stage, [])
        if capitulo not in caps:
            caps.append(capitulo)
            caps.sort()
        _save_status(status)


def get_status(libro: str | None = None) -> dict:
    """
    Si libro es None -> devuelve todo.
    Si libro se pasa -> devuelve solo ese libro (o {}).
    """
    status = _load_status()
    if libro is None:
        return status
    return status.get(libro.lower(), {})


def next_pending(libro: str, stage: str) -> int | None:
    """
    Devuelve el siguiente capítulo “obvio” a correr:
    max(hechos) + 1, o 1 si no hay nada.
    No valida contra cantidad real de capítulos, solo secuencia.
    """
    book = get_status(libro)
    caps = book.get(stage, [])
    if not caps:
        return 1
    return max(caps) + 1
