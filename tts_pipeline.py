# tts_pipeline.py
from pathlib import Path
from typing import List, Dict, Any

from pipeline_cancel import should_cancel


def extraer_guiones_para_tts(resultados: list) -> List[Dict[str, str]]:
    """
    Toma la lista de 'resultados' (salida del pipeline LLM) y construye
    un lote de guiones listos para TTS.
    """
    lote: List[Dict[str, str]] = []
    if not isinstance(resultados, list):
        print("⚠️ 'resultados' no es una lista.")
        return lote

    for item in resultados:
        tipo = (item.get("tipo") or "VIDEO").strip()
        referencia = (item.get("referencia") or "Capitulo").replace(":", "_").replace(" ", "_")
        nombre = f"{referencia}_{tipo}"
        # Sanitizar nombre de archivo
        nombre = "".join(c for c in nombre if c.isalnum() or c in ("_", "-"))

        guion = (item.get("guion_tts") or "").strip()
        if guion:
            lote.append(
                {
                    "tipo": tipo,
                    "nombre": nombre,
                    "guion_final": guion,
                }
            )
    return lote


def generar_audio_tts(
    client_eleven,
    texto: str,
    filename: str,
    voice_id: str = "NOpBlnGInO9m6vDvFkFC",
    model_id: str = "eleven_turbo_v2_5",
    output_folder: str = "tts_outputs",
    **voice_settings,
) -> Dict[str, Any]:
    """
    Genera un solo archivo de audio TTS y devuelve un dict con status y path.
    """
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    final_path = output_path / f"{filename}.mp3"

    try:
        default_settings = {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
            "speed": 1.0,
        }
        settings = {**default_settings, **voice_settings}

        # Check de cancel justo antes de pegarle a la API
        if should_cancel():
            print(f"⛔ Cancelado antes de generar audio para {filename}.")
            return {"status": "cancelled", "file": str(final_path)}

        audio_stream = client_eleven.text_to_speech.convert(
            voice_id=voice_id,
            text=texto,
            model_id=model_id,
            voice_settings=settings,
        )

        with open(final_path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)

        print(f"🎧 Audio generado: {final_path}")
        return {"status": "success", "file": str(final_path)}

    except Exception as e:
        print(f"❌ Error TTS {filename}: {e}")
        return {"status": "error", "message": str(e)}


def procesar_lote_audios(
    client_eleven,
    lista_guiones: List[Dict[str, str]],
    base_output: str = "tts_outputs",
    **voice_settings,
) -> Dict[str, Any]:
    """
    Procesa un lote de guiones y genera sus audios.
    Devuelve:
      {
        "procesados": [ {status, file}, ... ],
        "errores": [ {nombre, error}, ... ],
        "cancelled": bool
      }
    """
    reporte: Dict[str, Any] = {"procesados": [], "errores": [], "cancelled": False}

    if not lista_guiones:
        print("⚠️ No hay guiones para TTS (lista_guiones vacía).")
        return reporte

    for item in lista_guiones:
        if should_cancel():
            print("⛔ Cancelado por el usuario durante TTS.")
            reporte["cancelled"] = True
            break

        tipo = item.get("tipo", "OTRO")
        nombre = item.get("nombre", "sin_nombre")
        texto = item.get("guion_final", "")

        carpeta_tipo = Path(base_output) / tipo

        resultado = generar_audio_tts(
            client_eleven=client_eleven,
            texto=texto,
            filename=nombre,
            output_folder=str(carpeta_tipo),
            **voice_settings,
        )

        if resultado["status"] == "success":
            reporte["procesados"].append(resultado)
        elif resultado["status"] == "cancelled":
            # Marcamos cancel y salimos – no tiene sentido seguir
            reporte["cancelled"] = True
            break
        else:
            reporte["errores"].append(
                {
                    "nombre": nombre,
                    "error": resultado.get("message", "Error desconocido en TTS"),
                }
            )

    return reporte
