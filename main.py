# main.py
from pathlib import Path
import json

from config import client_mistral, client_eleven, BIBLE_JSON_PATH
from prompts import (
    PRINCIPAL_PROMPT,
    SYSTEM_PROMPT_REFINER,
    SYSTEM_PROMPT_ELEVEN_V3,
    SYSTEM_PROMPT_SCRIPT_DOCTOR,
)
from bible_io import BibleJSONProcessor
from llm_pipeline import procesar_capitulo
from tts_pipeline import extraer_guiones_para_tts, procesar_lote_audios
from image_pipeline import cargar_zimage_pipeline, generar_imagenes_desde_json
from pipeline_status import mark_stage_done
from pipeline_cancel import should_cancel


def guardar_json(data, filename: str):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"Archivo JSON guardado como: {filename}")


# ============ ETAPA 1: JSON (LLM) ============

def run_json(libro: str, capitulo: int):
    """
    Genera el JSON completo (con prompts y guion_tts) y lo guarda en disco.
    No genera audios ni imágenes.
    """
    print(f"=== [JSON] Iniciando para {libro} {capitulo} ===")

    processor = BibleJSONProcessor(BIBLE_JSON_PATH)
    texto = processor.format_chapter(libro, capitulo)
    print(texto)

    resultados = procesar_capitulo(
        client_mistral,
        PRINCIPAL_PROMPT,
        SYSTEM_PROMPT_REFINER,
        SYSTEM_PROMPT_SCRIPT_DOCTOR,
        SYSTEM_PROMPT_ELEVEN_V3,
        texto,
    )

    # Si se canceló o no hubo nada, NO intentes guardar archivo
    if should_cancel() or not resultados:
        print(f"=== [JSON] Cancelado o vacío para {libro} {capitulo} ===")
        return {
            "libro": libro,
            "capitulo": capitulo,
            "json_path": None,
            "num_items": len(resultados) if resultados else 0,
            "resultados": resultados or [],
        }

    out_json = f"{libro}_{capitulo}_videos.json"
    guardar_json(resultados, out_json)

    num_items = len(resultados)
    mark_stage_done(libro, capitulo, "json")
    print(f"=== [JSON] Terminado {libro} {capitulo} – items: {num_items} ===")

    return {
        "libro": libro,
        "capitulo": capitulo,
        "json_path": out_json,
        "num_items": num_items,
        "resultados": resultados,
    }


# ============ ETAPA 2: TTS (audios ElevenLabs) ============

def run_tts_from_resultados(resultados, libro: str, capitulo: int):
    """
    Genera audios TTS a partir de la lista 'resultados' en memoria.
    Respeta señal de cancelación.
    """
    print(f"=== [TTS] Iniciando para {libro} {capitulo} (desde memoria) ===")

    if should_cancel():
        print(f"=== [TTS] Cancelado antes de procesar para {libro} {capitulo} ===")
        return {
            "libro": libro,
            "capitulo": capitulo,
            "num_audios": 0,
            "audio_files": [],
        }

    lote_tts = extraer_guiones_para_tts(resultados)
    reporte_tts = procesar_lote_audios(
        client_eleven,
        lote_tts,
        voice_id="NOpBlnGInO9m6vDvFkFC",
        model_id="eleven_flash_v2_5",
        speed=1.1,
        stability=0.6,
        similarity_boost=0.9,
        style=0.2,
        use_speaker_boost=True,
    )
    num_audios = len(reporte_tts["procesados"])

    if should_cancel():
        print(f"=== [TTS] Cancelado después de generar audios para {libro} {capitulo} ===")
        # No marcamos stage_done si se canceló a mitad
        audio_files = [item["file"] for item in reporte_tts["procesados"]]
        return {
            "libro": libro,
            "capitulo": capitulo,
            "num_audios": num_audios,
            "audio_files": audio_files,
        }

    mark_stage_done(libro, capitulo, "tts")
    print(f"=== [TTS] Terminado {libro} {capitulo} – audios: {num_audios} ===")

    audio_files = [item["file"] for item in reporte_tts["procesados"]]

    return {
        "libro": libro,
        "capitulo": capitulo,
        "num_audios": num_audios,
        "audio_files": audio_files,
    }


def run_tts_from_json(libro: str, capitulo: int):
    """
    Genera audios TTS cargando el JSON previamente generado.
    Respeta señal de cancelación.
    """
    json_path = Path(f"{libro}_{capitulo}_videos.json")
    if not json_path.exists():
        raise FileNotFoundError(f"No existe el JSON: {json_path}")

    print(f"=== [TTS] Iniciando para {libro} {capitulo} desde {json_path} ===")

    if should_cancel():
        print(f"=== [TTS] Cancelado antes de abrir JSON para {libro} {capitulo} ===")
        return {
            "libro": libro,
            "capitulo": capitulo,
            "json_path": str(json_path),
            "num_audios": 0,
            "audio_files": [],
        }

    with json_path.open("r", encoding="utf-8") as f:
        resultados = json.load(f)

    tts_info = run_tts_from_resultados(resultados, libro, capitulo)

    return {
        **tts_info,
        "json_path": str(json_path),
    }


# ============ ETAPA 1+2: JSON + TTS ============

def run_json_tts(libro: str, capitulo: int):
    """
    Ejecuta JSON (LLM) y luego TTS, usando resultados en memoria.
    No genera imágenes.
    Respeta señal de cancelación.
    """
    info_json = run_json(libro, capitulo)

    # Si se canceló o no hay resultados, no seguimos a TTS
    if should_cancel() or not info_json.get("resultados"):
        print(f"=== [JSON+TTS] Cortado tras JSON para {libro} {capitulo} ===")
        return {
            "libro": libro,
            "capitulo": capitulo,
            "json_path": info_json.get("json_path"),
            "num_items": info_json.get("num_items", 0),
            "num_audios": 0,
            "audio_files": [],
        }

    info_tts = run_tts_from_resultados(info_json["resultados"], libro, capitulo)

    return {
        "libro": libro,
        "capitulo": capitulo,
        "json_path": info_json["json_path"],
        "num_items": info_json["num_items"],
        "num_audios": info_tts["num_audios"],
        "audio_files": info_tts["audio_files"],
    }


# ============ ETAPA 3: IMÁGENES ============

def run_imagenes_from_json(libro: str, capitulo: int, output_root: str = "output"):
    """
    Carga Z-Image y genera imágenes a partir del JSON correspondiente al libro/capítulo.
    Respeta señal de cancelación.
    """
    json_path = Path(f"{libro}_{capitulo}_videos.json")
    if not json_path.exists():
        raise FileNotFoundError(f"No existe el JSON: {json_path}")

    print(f"=== [IMG] Iniciando imágenes para {libro} {capitulo} desde {json_path} ===")

    if should_cancel():
        print(f"=== [IMG] Cancelado antes de generar imágenes para {libro} {capitulo} ===")
        return {
            "libro": libro,
            "capitulo": capitulo,
            "json_path": str(json_path),
            "output_root": output_root,
        }

    pipeline = cargar_zimage_pipeline()
    generar_imagenes_desde_json(pipeline, str(json_path), output_root=output_root)

    if should_cancel():
        print(f"=== [IMG] Cancelado después de generar algunas imágenes para {libro} {capitulo} ===")
        # No marcamos stage_done si se canceló a mitad
        return {
            "libro": libro,
            "capitulo": capitulo,
            "json_path": str(json_path),
            "output_root": output_root,
        }

    mark_stage_done(libro, capitulo, "imagenes")

    print(f"=== [IMG] Terminado imágenes para {libro} {capitulo} ===")

    return {
        "libro": libro,
        "capitulo": capitulo,
        "json_path": str(json_path),
        "output_root": output_root,
    }


# ============ FULL: JSON + TTS + IMÁGENES ============

def run_full(libro: str, capitulo: int):
    """
    Ejecuta JSON + TTS + IMÁGENES en cadena.
    Respeta señal de cancelación.
    """
    print(f"=== [FULL] Iniciando pipeline completo para {libro} {capitulo} ===")

    if should_cancel():
        print(f"=== [FULL] Cancelado antes de iniciar para {libro} {capitulo} ===")
        return {
            "libro": libro,
            "capitulo": capitulo,
            "json_path": f"{libro}_{capitulo}_videos.json",
            "num_items": 0,
            "num_audios": 0,
            "audio_files": [],
            "output_root": "output",
        }

    info_json_tts = run_json_tts(libro, capitulo)

    if should_cancel() or info_json_tts.get("num_items", 0) == 0:
        print(f"=== [FULL] Cortado tras JSON+TTS para {libro} {capitulo} ===")
        # No marcamos "full" si no llegamos a imágenes
        return {
            **info_json_tts,
            "output_root": "output",
        }

    info_img = run_imagenes_from_json(libro, capitulo, output_root="output")

    if should_cancel():
        print(f"=== [FULL] Cancelado después de imágenes para {libro} {capitulo} ===")
        # No marcamos full si se canceló justo al final
        return {
            **info_json_tts,
            "output_root": info_img["output_root"],
        }

    mark_stage_done(libro, capitulo, "full")
    print(f"=== [FULL] Terminado pipeline completo para {libro} {capitulo} ===")

    return {
        **info_json_tts,
        "output_root": info_img["output_root"],
    }


def main():
    # Ejemplo modo local:
    libro = "genesis"
    capitulo = 9
    resumen = run_full(libro, capitulo)
    print(resumen)


if __name__ == "__main__":
    main()

