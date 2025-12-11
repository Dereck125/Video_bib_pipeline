import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime

# Estructura de la Biblia
BIBLE_STRUCTURE = {
    "genesis": 50, "exodo": 40, "levitico": 27, "numeros": 36, "deuteronomio": 34,
    "josue": 24, "jueces": 21, "rut": 4, "1-samuel": 31, "2-samuel": 24,
    "1-reyes": 22, "2-reyes": 25, "1-cronicas": 29, "2-cronicas": 36,
    "esdras": 10, "nehemias": 13, "ester": 10, "job": 42, "salmos": 150,
    "proverbios": 31, "eclesiastes": 12, "cantares": 8, "isaias": 66,
    "jeremias": 52, "lamentaciones": 5, "ezequiel": 48, "daniel": 12,
    "oseas": 14, "joel": 3, "amos": 9, "abdias": 1, "jonas": 4, "miqueas": 7,
    "nahum": 3, "habacuc": 3, "sofonias": 3, "hageo": 2, "zacarias": 14,
    "malaquias": 4, "mateo": 28, "marcos": 16, "lucas": 24, "juan": 21,
    "hechos": 28, "romanos": 16, "1-corintios": 16, "2-corintios": 13,
    "galatas": 6, "efesios": 6, "filipenses": 4, "colosenses": 4,
    "1-tesalonicenses": 5, "2-tesalonicenses": 3, "1-timoteo": 6,
    "2-timoteo": 4, "tito": 3, "filemon": 1, "hebreos": 13, "santiago": 5,
    "1-pedro": 5, "2-pedro": 3, "1-juan": 5, "2-juan": 1, "3-juan": 1,
    "judas": 1, "apocalipsis": 22
}

class BibleScraper:
    def __init__(self, headless=True, delay=0.5):
        self.headless = headless
        self.delay = delay
        self.base_url = "https://www.biblia.es/biblia-buscar-libros-1.php"
        self.version = "rv60"
        self.bible_data = {}
        self.stats = {"success": 0, "errors": 0, "total": 0}
        
    def parse_verses(self, text):
        """Extrae versículos del texto usando regex"""
        verses = {}
        
        # Limpiar el texto
        text = text.strip()
        
        # Patrón para detectar versículos: número seguido de texto
        # Formato: "1Texto del versículo" o "1 Texto del versículo"
        pattern = r'(\d+)\s*([^0-9]+?)(?=\d+\s*[A-ZÁÉÍÓÚÑ]|$)'
        
        matches = re.finditer(pattern, text, re.DOTALL)
        
        for match in matches:
            verse_num = match.group(1)
            verse_text = match.group(2).strip()
            
            # Limpiar texto del versículo
            verse_text = re.sub(r'\s+', ' ', verse_text)
            verse_text = verse_text.strip()
            
            if verse_text:
                verses[verse_num] = verse_text
        
        return verses
        
    async def scrape_chapter(self, page, book, chapter):
        """Extrae un capítulo específico"""
        url = f"{self.base_url}?libro={book}&capitulo={chapter}&version={self.version}"
        
        try:
            self.stats["total"] += 1
            
            # Navegar a la página
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            if response.status != 200:
                print(f"  ✗ Error HTTP {response.status}: {book} {chapter}")
                self.stats["errors"] += 1
                return {}
            
            # Esperar a que cargue el contenido
            await page.wait_for_load_state("networkidle", timeout=10000)
            
            # Método 1: Buscar en el main content
            verses = {}
            main_content = await page.query_selector('main')
            
            if main_content:
                text = await main_content.inner_text()
                verses = self.parse_verses(text)
            
            # Método 2: Si no encuentra nada, buscar en todo el body
            if not verses:
                body = await page.query_selector('body')
                if body:
                    text = await body.inner_text()
                    # Extraer solo la sección relevante (después de "Capítulo X")
                    chapter_pattern = f"Capítulo {chapter}"
                    if chapter_pattern in text:
                        text = text.split(chapter_pattern, 1)[1]
                        # Tomar hasta el siguiente "Capítulo" o hasta el final
                        next_chapter = text.find("Capítulo")
                        if next_chapter > 0:
                            text = text[:next_chapter]
                    
                    verses = self.parse_verses(text)
            
            if verses:
                print(f"  ✓ {book.title():20} Cap {chapter:3}: {len(verses):3} versículos")
                self.stats["success"] += 1
            else:
                print(f"  ⚠ {book.title():20} Cap {chapter:3}: No se encontraron versículos")
                self.stats["errors"] += 1
            
            return verses
            
        except PlaywrightTimeoutError:
            print(f"  ✗ Timeout: {book} {chapter}")
            self.stats["errors"] += 1
            return {}
        except Exception as e:
            print(f"  ✗ Error en {book} {chapter}: {str(e)[:50]}")
            self.stats["errors"] += 1
            return {}
    
    async def scrape_book(self, page, book, num_chapters):
        """Extrae todos los capítulos de un libro"""
        print(f"\n{'='*60}")
        print(f"📖 {book.upper()} ({num_chapters} capítulos)")
        print('='*60)
        
        book_data = {}
        for chapter in range(1, num_chapters + 1):
            verses = await self.scrape_chapter(page, book, chapter)
            book_data[str(chapter)] = verses
            
            # Delay para no sobrecargar el servidor
            await asyncio.sleep(self.delay)
        
        return book_data
    
    async def scrape_all(self, start_from=None, limit=None, books_list=None):
        """Extrae toda la Biblia o libros específicos"""
        async with async_playwright() as p:
            print("🚀 Iniciando scraper de la Biblia Reina Valera 1960")
            print("="*60)
            
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            # Determinar qué libros extraer
            if books_list:
                books = [(book, BIBLE_STRUCTURE[book]) for book in books_list if book in BIBLE_STRUCTURE]
            else:
                books = list(BIBLE_STRUCTURE.items())
            
            # Comenzar desde un libro específico
            if start_from:
                start_idx = next((i for i, (book, _) in enumerate(books) if book == start_from), 0)
                books = books[start_idx:]
            
            # Limitar cantidad de libros
            if limit:
                books = books[:limit]
            
            total_books = len(books)
            start_time = datetime.now()
            
            for idx, (book, num_chapters) in enumerate(books, 1):
                print(f"\n📚 Progreso: {idx}/{total_books} libros")
                self.bible_data[book] = await self.scrape_book(page, book, num_chapters)
                
                # Guardar progreso cada 5 libros
                if idx % 5 == 0:
                    self.save_progress(f"biblia_progreso_{idx}_libros.json")
            
            await browser.close()
            
            # Estadísticas finales
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            print("\n" + "="*60)
            print("✅ SCRAPING COMPLETADO")
            print("="*60)
            print(f"⏱️  Tiempo total: {duration:.2f} segundos")
            print(f"📊 Capítulos exitosos: {self.stats['success']}")
            print(f"❌ Capítulos con error: {self.stats['errors']}")
            print(f"📈 Total intentado: {self.stats['total']}")
            print(f"✨ Tasa de éxito: {(self.stats['success']/self.stats['total']*100):.1f}%")
    
    def save_progress(self, filename="biblia_reina_valera_1960.json"):
        """Guarda el progreso en JSON"""
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        filepath = output_dir / filename
        
        # Calcular estadísticas
        total_chapters = sum(len(chapters) for chapters in self.bible_data.values())
        total_verses = sum(
            len(verses) 
            for book in self.bible_data.values() 
            for verses in book.values()
        )
        
        data = {
            "metadata": {
                "version": "Reina Valera 1960",
                "fecha_extraccion": datetime.now().isoformat(),
                "total_libros": len(self.bible_data),
                "total_capitulos": total_chapters,
                "total_versiculos": total_verses,
                "fuente": "https://www.biblia.es"
            },
            "libros": self.bible_data
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        size_kb = filepath.stat().st_size / 1024
        print(f"\n💾 Guardado: {filepath}")
        print(f"   📚 Libros: {len(self.bible_data)}")
        print(f"   📖 Capítulos: {total_chapters}")
        print(f"   📝 Versículos: {total_verses}")
        print(f"   💿 Tamaño: {size_kb:.2f} KB")
    
    def save_by_book(self):
        """Guarda cada libro en un archivo JSON separado"""
        output_dir = Path("output/por_libro")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for book, chapters in self.bible_data.items():
            filepath = output_dir / f"{book}.json"
            
            total_verses = sum(len(verses) for verses in chapters.values())
            
            data = {
                "metadata": {
                    "libro": book,
                    "version": "Reina Valera 1960",
                    "total_capitulos": len(chapters),
                    "total_versiculos": total_verses,
                    "fecha_extraccion": datetime.now().isoformat()
                },
                "capitulos": chapters
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ {len(self.bible_data)} libros guardados en {output_dir}")


async def main():
    """Función principal con diferentes modos de uso"""
    
    # MODO 1: PRUEBA RÁPIDA (solo 1 libro)
    #print("🧪 MODO PRUEBA: Extrayendo solo Génesis...")
    #scraper = BibleScraper(headless=False, delay=0.3)
    #await scraper.scrape_all(books_list=["genesis"])
    #scraper.save_progress("test_genesis.json")
    
    # MODO 2: PRUEBA MEDIANA (primeros 3 libros)
    # scraper = BibleScraper(headless=True, delay=0.5)
    # await scraper.scrape_all(limit=3)
    # scraper.save_progress("test_3_libros.json")
    
    # MODO 3: EXTRAER TODO EL ANTIGUO TESTAMENTO
    # antiguo_testamento = [
    #     "genesis", "exodo", "levitico", "numeros", "deuteronomio",
    #     "josue", "jueces", "rut", "1-samuel", "2-samuel",
    #     "1-reyes", "2-reyes", "1-cronicas", "2-cronicas",
    #     "esdras", "nehemias", "ester", "job", "salmos",
    #     "proverbios", "eclesiastes", "cantares", "isaias",
    #     "jeremias", "lamentaciones", "ezequiel", "daniel",
    #     "oseas", "joel", "amos", "abdias", "jonas", "miqueas",
    #     "nahum", "habacuc", "sofonias", "hageo", "zacarias", "malaquias"
    # ]
    # scraper = BibleScraper(headless=True, delay=0.5)
    # await scraper.scrape_all(books_list=antiguo_testamento)
    # scraper.save_progress("antiguo_testamento.json")
    # scraper.save_by_book()
    
    # MODO 4: EXTRAER TODA LA BIBLIA
    #scraper = BibleScraper(headless=True, delay=0.5)
    #await scraper.scrape_all()
    #scraper.save_progress("biblia_completa_rv1960.json")
    #scraper.save_by_book()
    
    # MODO 5: CONTINUAR DESDE UN LIBRO ESPECÍFICO
    # scraper = BibleScraper(headless=True, delay=0.5)
    # await scraper.scrape_all(start_from="mateo")
    # scraper.save_progress("nuevo_testamento.json")
    
    print("\n🎉 ¡Proceso completado!")


if __name__ == "__main__":
    asyncio.run(main())