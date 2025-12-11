# telegram_bot.py
import os
import asyncio
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from pipeline_status import get_status, next_pending
from pipeline_cancel import reset_cancel, request_cancel
from main import (
    run_json,
    run_tts_from_json,
    run_json_tts,
    run_imagenes_from_json,
    run_full,
)

from config import BIBLE_JSON_PATH
from bible_io import BibleJSONProcessor

processor = BibleJSONProcessor(BIBLE_JSON_PATH)


load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")




async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos disponibles:\n"
        "/json <cap>              – Solo generar JSON (por defecto genesis)\n"
        "/json <libro> <cap>      – Solo generar JSON para libro/capítulo\n"
        "/tts <cap>               – Solo TTS (requiere JSON previo)\n"
        "/tts <libro> <cap>       – Solo TTS para libro/capítulo\n"
        "/json_tts <...>          – JSON + TTS\n"
        "/imagenes <...>          – Solo imágenes (requiere JSON previo)\n"
        "/full <...>              – JSON + TTS + imágenes\n"
        "/libros                  – Lista de libros\n"
        "/capitulos <libro>       – Lista capítulos de un libro\n"
        "/status [libro]          – Estado de progreso (por defecto genesis)\n"
        "/cancel                  – Solicita cancelar el proceso en curso"
    )


def _validar_libro_y_capitulo(libro: str, capitulo: int):
    caps = processor.list_chapters(libro)
    if not caps:
        raise ValueError(f"El libro '{libro}' no existe en el JSON.")
    if capitulo not in caps:
        raise ValueError(f"El capítulo {capitulo} no existe en el libro '{libro}'.")


async def cmd_libros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    libros = processor.list_books()
    if not libros:
        await update.message.reply_text("No encontré libros en el JSON.")
        return

    lines = []
    for libro in libros:
        n_caps = processor.chapter_count(libro)
        lines.append(f"- {libro} ({n_caps} capítulos)")

    texto = "Libros disponibles:\n" + "\n".join(lines)
    await update.message.reply_text(texto)

def _parse_libro_capitulo(args):
    """
    Formatos aceptados:
    - /comando 9              -> libro = 'genesis', cap = 9
    - /comando exodo 3        -> libro = 'exodo', cap = 3
    """
    if not args:
        raise ValueError("Debes indicar el capítulo, por ejemplo: 9 o <libro> <cap> (ej: exodo 3).")

    if len(args) == 1:
        # Solo capítulo, default a 'genesis'
        libro = "genesis"
        cap_str = args[0]
    else:
        # libro + capítulo
        libro = args[0].lower()
        cap_str = args[1]

    try:
        capitulo = int(cap_str)
    except ValueError:
        raise ValueError("El capítulo debe ser un número entero.")

    return libro, capitulo

async def cmd_capitulos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /capitulos <libro>. Ej: /capitulos genesis")
        return

    libro = context.args[0].lower()
    caps = processor.list_chapters(libro)

    if not caps:
        await update.message.reply_text(f"No encontré capítulos para el libro '{libro}'.")
        return

    rango = f"{caps[0]}–{caps[-1]}" if len(caps) > 1 else f"{caps[0]}"
    texto = (
        f"Libro: {libro}\n"
        f"Capítulos disponibles: {', '.join(str(c) for c in caps)}\n"
        f"Rango: {rango}"
    )
    await update.message.reply_text(texto)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /status            -> asume "genesis"
    # /status exodo      -> usa "exodo"
    args = context.args
    libro = args[0].lower() if args else "genesis"

    status = get_status(libro)

    if not status:
        await update.message.reply_text(f"No hay registros para el libro '{libro}'.")
        return

    def _fmt(caps):
        if not caps:
            return "-"
        return ", ".join(str(c) for c in sorted(caps))

    json_caps = status.get("json", [])
    tts_caps = status.get("tts", [])
    img_caps = status.get("imagenes", [])
    full_caps = status.get("full", [])

    next_json = next_pending(libro, "json")
    next_tts = next_pending(libro, "tts")
    next_img = next_pending(libro, "imagenes")

    texto = (
        f"Estado para {libro}:\n"
        f"- JSON:      { _fmt(json_caps) }\n"
        f"- TTS:       { _fmt(tts_caps) }\n"
        f"- Imágenes:  { _fmt(img_caps) }\n"
        f"- Full:      { _fmt(full_caps) }\n\n"
        f"Siguientes sugeridos:\n"
        f"- Próximo JSON:      {next_json}\n"
        f"- Próximo TTS:       {next_tts}\n"
        f"- Próximas imágenes: {next_img}\n"
    )


    await update.message.reply_text(texto)
# ========== /json ==========

async def cmd_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_cancel()  # ya está importado arriba
    chat_id = update.effective_chat.id

    try:
        libro, capitulo = _parse_libro_capitulo(context.args)
        _validar_libro_y_capitulo(libro, capitulo)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(f"[JSON] Iniciando para {libro} {capitulo}...")

    loop = asyncio.get_running_loop()
    run_fn = partial(run_json, libro, capitulo)
    resumen = await loop.run_in_executor(None, run_fn)

    # Puede venir cancelado o vacío
    json_path_str = resumen.get("json_path")
    num_items = resumen.get("num_items", 0)

    if not json_path_str:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"[JSON] Proceso cancelado o sin contenido para {libro} {capitulo}. No se generó archivo.",
        )
        return

    json_path = Path(json_path_str).resolve()
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"[JSON] Terminado {libro} {capitulo}. Items: {num_items}. Te envío el archivo.",
    )

    if json_path.exists():
        with json_path.open("rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=json_path.name,
                caption=f"JSON de {libro} {capitulo}",
            )


# ========== /tts ==========

async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    reset_cancel()
    chat_id = update.effective_chat.id
    try:
        libro, capitulo = _parse_libro_capitulo(context.args)
        # opcional: _validar_libro_y_capitulo(libro, capitulo)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(f"[TTS] Iniciando para {libro} {capitulo} (desde JSON existente)...")

    loop = asyncio.get_running_loop()
    run_fn = partial(run_tts_from_json, libro, capitulo)
    try:
        resumen = await loop.run_in_executor(None, run_fn)
    except FileNotFoundError as e:
        await update.message.reply_text(str(e))
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"[TTS] Terminado {libro} {capitulo}.\n"
            f"Audios generados: {resumen['num_audios']}.\n"
            f"Te envío los audios."
        ),
    )

    # Enviar audios
    for audio_path in resumen.get("audio_files", []):
        p = Path(audio_path)
        if p.exists():
            with p.open("rb") as f:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    filename=p.name,
                    caption=f"{libro} {capitulo} – {p.name}",
                )



# ========== /json_tts ==========

async def cmd_json_tts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_cancel()
    chat_id = update.effective_chat.id

    try:
        libro, capitulo = _parse_libro_capitulo(context.args)
        # opcional: _validar_libro_y_capitulo(libro, capitulo)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(f"[JSON+TTS] Iniciando para {libro} {capitulo}...")

    loop = asyncio.get_running_loop()
    run_fn = partial(run_json_tts, libro, capitulo)
    resumen = await loop.run_in_executor(None, run_fn)

    json_path_str = resumen.get("json_path")
    num_items = resumen.get("num_items", 0)
    num_audios = resumen.get("num_audios", 0)

    if not json_path_str:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"[JSON+TTS] Proceso cancelado o sin JSON para {libro} {capitulo}.",
        )
        return

    json_path = Path(json_path_str).resolve()
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"[JSON+TTS] Terminado {libro} {capitulo}.\n"
            f"Items: {num_items} – Audios: {num_audios}.\n"
            f"Te envío el JSON y los audios."
        ),
    )

    # Enviar JSON
    if json_path.exists():
        with json_path.open("rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=json_path.name,
                caption=f"JSON de {libro} {capitulo}",
            )

    # Enviar audios
    for audio_path in resumen.get("audio_files", []):
        p = Path(audio_path)
        if p.exists():
            with p.open("rb") as f:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    filename=p.name,
                    caption=f"{libro} {capitulo} – {p.name}",
                )


# ========== /imagenes ==========

async def cmd_imagenes(update: Update, context: ContextTypes.DEFAULT_TYPE):

    reset_cancel()
    chat_id = update.effective_chat.id
    try:
        libro, capitulo = _parse_libro_capitulo(context.args)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(
        f"[IMG] Iniciando generación de imágenes para {libro} {capitulo} (requiere JSON previo)..."
    )

    loop = asyncio.get_running_loop()
    run_fn = partial(run_imagenes_from_json, libro, capitulo, "output")
    try:
        resumen = await loop.run_in_executor(None, run_fn)
    except FileNotFoundError as e:
        await update.message.reply_text(str(e))
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"[IMG] Terminado {libro} {capitulo}.\n"
            f"Imágenes en carpeta: {resumen['output_root']}/"
        ),
    )


# ========== /full ==========

async def cmd_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_cancel()
    chat_id = update.effective_chat.id

    try:
        libro, capitulo = _parse_libro_capitulo(context.args)
        _validar_libro_y_capitulo(libro, capitulo)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(f"[FULL] Iniciando JSON + TTS + IMÁGENES para {libro} {capitulo}...")

    loop = asyncio.get_running_loop()
    run_fn = partial(run_full, libro, capitulo)
    resumen = await loop.run_in_executor(None, run_fn)

    json_path_str = resumen.get("json_path")
    num_items = resumen.get("num_items", 0)
    num_audios = resumen.get("num_audios", 0)
    output_root = resumen.get("output_root", "output")

    if not json_path_str:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"[FULL] Proceso cancelado o sin JSON para {libro} {capitulo}.",
        )
        return

    json_path = Path(json_path_str).resolve()
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"[FULL] Terminado {libro} {capitulo}.\n"
            f"Items: {num_items} – Audios: {num_audios}.\n"
            f"Imágenes en: {output_root}/.\n"
            f"Te envío el JSON y los audios."
        ),
    )

    # JSON
    if json_path.exists():
        with json_path.open("rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=json_path.name,
                caption=f"JSON de {libro} {capitulo}",
            )

    # Audios
    for audio_path in resumen.get("audio_files", []):
        p = Path(audio_path)
        if p.exists():
            with p.open("rb") as f:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    filename=p.name,
                    caption=f"{libro} {capitulo} – {p.name}",
                )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request_cancel()
    await update.message.reply_text(
        "Cancelación solicitada. El proceso se detendrá en cuanto termine el paso actual."
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el .env")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("json", cmd_json))
    app.add_handler(CommandHandler("tts", cmd_tts))
    app.add_handler(CommandHandler("json_tts", cmd_json_tts))
    app.add_handler(CommandHandler("imagenes", cmd_imagenes))
    app.add_handler(CommandHandler("full", cmd_full))
    app.add_handler(CommandHandler("libros", cmd_libros))
    app.add_handler(CommandHandler("capitulos", cmd_capitulos))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    print("Bot de Telegram corriendo...")
    app.run_polling()


if __name__ == "__main__":
    main()
