# bible_io.py
import json
from pathlib import Path

def log(msg: str):
    print(f"[LOG] {msg}")

def sanitize_text(txt: str, max_words: int = 3000) -> str:
    words = txt.split()
    return " ".join(words[:max_words])

def retry(fn, attempts: int = 3, backoff: float = 1.5):
    import time, random
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            time.sleep(backoff**i + random.uniform(0, 0.2))

class BibleJSONProcessor:
    def __init__(self, json_path: str | Path):
        self.json_path = Path(json_path)
        self.data = None
        self.load_json()

    def load_json(self):
        with open(self.json_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def get_chapter(self, book: str, chapter: int):
        books = self.data.get("libros", {})
        return books.get(book, {}).get(str(chapter), None)

    def format_chapter(self, book: str, chapter: int, include_numbers: bool = True) -> str:
        data = self.get_chapter(book, chapter)
        if not data:
            return ""

        header = f"{book} - Capítulo {chapter}\n" + "=" * 40 + "\n\n"

        # Nos quedamos solo con las claves que realmente son versículos (números)
        verses = {
            k: v for k, v in data.items()
            if isinstance(k, str) and k.isdigit()
        }

        if not verses:
            # Si por alguna razón no hay versículos numéricos, regresamos solo el header
            return header.strip()

        # Ordenamos por número de versículo
        sorted_items = sorted(verses.items(), key=lambda x: int(x[0]))

        lines = [
            f"{num}. {texto}" if include_numbers else texto
            for num, texto in sorted_items
        ]

        return header + "\n".join(lines)

    # NUEVO: lista los libros
    def list_books(self):
        return list(self.data.get("libros", {}).keys())

    # NUEVO: número de capítulos de un libro
    def chapter_count(self, book: str) -> int:
        libros = self.data.get("libros", {})
        if book not in libros:
            return 0
        return len(libros[book])

    # NUEVO: lista capítulos disponibles de un libro
    def list_chapters(self, book: str):
        libros = self.data.get("libros", {})
        caps = libros.get(book, {})
        return sorted(int(c) for c in caps.keys() if c.isdigit())