# llm_pipeline.py
import json
from typing import List, Dict, Any

from pipeline_cancel import should_cancel
from bible_io import sanitize_text, retry, log


def validate_video_structure(item: dict) -> bool:
    """
    Valida que el bloque tenga la estructura mínima esperada
    para poder generar imágenes.
    """
    tipo = item.get("tipo", "DESCONOCIDO")

    # Caso ORACION: campos básicos para la imagen estática
    if tipo == "ORACION":
        return all(k in item for k in ["prompt_imagen", "texto_imagen", "oracion"])

    # Caso HISTORIA / CURIOSIDAD:
    if "secuencia_visual" not in item or "transiciones" not in item:
        return False

    for i in range(1, 7):
        if f"frame_{i}" not in item["secuencia_visual"]:
            return False

    for i in range(1, 6):
        if f"transicion_{i}_{i+1}" not in item["transiciones"]:
            return False

    return True


def generar_contenido_llm(
    client,
    principal_prompt: str,
    texto_capitulo: str,
    model: str = "mistral-small-latest",
    temperature: float = 0.6,
) -> Dict[str, Any]:
    """
    Primer llamado: genera la estructura base "contenido" a partir del capítulo.
    """
    if should_cancel():
        log("⛔ Cancelado antes de generar_contenido_llm.")
        return {}

    texto = sanitize_text(texto_capitulo)

    def call():
        response = client.chat.complete(
            model=model,
            messages=[
                {"role": "system", "content": principal_prompt},
                {"role": "user", "content": f"Capítulo a analizar:\n{texto}"},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return json.loads(response.choices[0].message.content)

    return retry(call)


def refinar_video_llm(
    client,
    system_prompt_refiner: str,
    video_data: dict,
    model: str = "mistral-small-latest",
    temperature: float = 0.6,
) -> Dict[str, Any]:
    """
    Traduce y refina los campos visuales a prompts técnicos.
    """
    if should_cancel():
        log("⛔ Cancelado antes de refinar_video_llm.")
        return video_data

    payload = json.dumps(video_data, ensure_ascii=False)

    def call():
        response = client.chat.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt_refiner},
                {
                    "role": "user",
                    "content": (
                        "Refine this video visuals (Leave Spanish text alone):\n"
                        f"{payload}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return json.loads(response.choices[0].message.content)

    return retry(call)


def expandir_guion_llm(
    client,
    system_prompt_script_doctor: str,
    video_data: dict,
    model: str = "mistral-medium-latest",
    temperature: float = 0.6,
    max_tokens: int = 800,
) -> str:
    """
    Convierte el texto base (guion/curiosidad/oracion) en un script finalizado
    para ser luego pasado a TTS.
    """
    texto_base = (
        video_data.get("guion")
        or video_data.get("curiosidad")
        or video_data.get("oracion")
    )

    if not texto_base:
        log("⚠️ expandir_guion_llm: texto_base vacío o inexistente.")
        return ""

    if should_cancel():
        log("⛔ Cancelado antes de expandir_guion_llm.")
        return ""

    user_content = f"""
    TIPO DE VIDEO: {video_data.get('tipo')}
    REFERENCIA: {video_data.get('referencia')}
    TEXTO BASE: {texto_base}
    """

    def call():
        response = client.chat.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt_script_doctor},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()

    return retry(call)


def generar_tts_llm(
    client,
    system_prompt_eleven_v3: str,
    tipo: str,
    guion: str,
    model: str = "mistral-medium-latest",
    temperature: float = 0.6,
    max_tokens: int = 800,
) -> str:
    """
    Ajusta el script expandido al formato óptimo para ElevenLabs.
    """
    if not guion:
        log("⚠️ generar_tts_llm: guion vacío; se omite ajuste para TTS.")
        return ""

    if should_cancel():
        log("⛔ Cancelado antes de generar_tts_llm.")
        return ""

    user_content = f"""
    TIPO: {tipo}
    GUION EXPANDIDO:
    {guion}
    """

    def call():
        response = client.chat.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt_eleven_v3},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()

    return retry(call)


def procesar_capitulo(
    client,
    PRINCIPAL_PROMPT,
    SYSTEM_PROMPT_REFINER,
    SYSTEM_PROMPT_SCRIPT_DOCTOR,
    SYSTEM_PROMPT_ELEVEN_V3,
    texto_capitulo: str,
    model_text: str = "mistral-medium-latest",
    model_script: str = "mistral-medium-latest",
    model_refiner: str = "mistral-small-latest",
    model_voice: str = "mistral-small-latest",
) -> List[Dict[str, Any]]:
    """
    Orquesta todo el pipeline LLM para un capítulo:
      1) Generar estructura base (contenido).
      2) Refinar prompts visuales.
      3) Expandir guión.
      4) Ajustar texto para TTS.
    Devuelve una lista de items listos para TTS + imagen.
    """
    log("Generando contenido base (Estructura + Conceptos en Español)...")

    contenido = generar_contenido_llm(
        client,
        PRINCIPAL_PROMPT,
        texto_capitulo,
        model=model_text,
    )

    resultados: List[Dict[str, Any]] = []

    items_list = contenido.get("contenido", [])
    if not items_list:
        log("❌ Error: El LLM no devolvió una lista en 'contenido'.")
        return resultados

    for item in items_list:
        if should_cancel():
            log("⛔ Cancelado por el usuario durante procesar_capitulo.")
            break

        tipo = item.get("tipo", "DESCONOCIDO")
        log(f"--- Procesando: {tipo} ---")

        # 1) Refinar visuales
        log("Refinando visuales (Traduciendo a Prompts de IA)...")
        refinado = refinar_video_llm(
            client,
            SYSTEM_PROMPT_REFINER,
            item,
            model=model_refiner,
        )

        if not validate_video_structure(refinado):
            log(
                f"⚠ JSON inválido en {tipo}, usando versión base "
                "(puede que los prompts no estén en inglés)"
            )
            refinado = item

        if should_cancel():
            log("⛔ Cancelado justo después de refinar visuales.")
            break

        # 2) Script Doctor
        log("Generando guion expandido (Script Doctor)...")
        guion_expandido = expandir_guion_llm(
            client,
            SYSTEM_PROMPT_SCRIPT_DOCTOR,
            refinado,
            model=model_script,
        )

        if not guion_expandido:
            log(f"⚠ No se pudo generar guion expandido para {tipo}, se omite TTS.")
            refinado["guion_tts"] = ""
            resultados.append(refinado)
            continue

        if should_cancel():
            log("⛔ Cancelado antes de optimizar para TTS.")
            break

        # 3) TTS-friendly
        log("Optimizando para TTS (Emotion Lite)...")
        guion_tts = generar_tts_llm(
            client,
            SYSTEM_PROMPT_ELEVEN_V3,
            tipo,
            guion_expandido,
            model=model_voice,
        )

        refinado["guion_tts"] = guion_tts
        resultados.append(refinado)

    return resultados
