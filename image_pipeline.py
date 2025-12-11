# image_pipeline.py
import json
import os
import gc
from pathlib import Path

import torch
from diffusers import ZImagePipeline, ZImageTransformer2DModel, GGUFQuantizationConfig

from pipeline_cancel import should_cancel
from config import ZIMAGE_GGUF


def cargar_zimage_pipeline(
    gguf_path: str | Path = ZIMAGE_GGUF,
    model_name: str = "Tongyi-MAI/Z-Image-Turbo",
    torch_dtype=torch.bfloat16,
    device: str = "cuda",
):
    gguf_path = Path(gguf_path)

    if not gguf_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo GGUF en: {gguf_path}")

    print("Cargando modelo Z-Image cuantizado Q8...")
    transformer = ZImageTransformer2DModel.from_single_file(
        gguf_path,
        quantization_config=GGUFQuantizationConfig(compute_dtype=torch_dtype),
        dtype=torch_dtype,
    )

    pipeline = ZImagePipeline.from_pretrained(
        model_name,
        transformer=transformer,
        dtype=torch_dtype,
    ).to(device)

    print("✅ Modelo cuantizado Q8 cargado\n")
    return pipeline


CONFIG = {
    "height": 1280,
    "width": 720,
    "num_inference_steps": 8,
    "guidance_scale": 0.0,
}


def generar_imagen(pipeline, prompt: str, carpeta: str | Path, nombre: str):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    print(f"Generando: {nombre}...")

    # Usa el mismo device que el pipeline
    device = next(pipeline.transformer.parameters()).device
    generator = torch.Generator(device=device).manual_seed(33442)

    with torch.inference_mode():
        img = pipeline(
            prompt=prompt,
            **CONFIG,
            generator=generator,
        ).images[0]

    ruta = carpeta / nombre
    img.save(ruta)
    print(f"✅ Guardado: {ruta}\n")

    del img
    torch.cuda.empty_cache()
    gc.collect()


def generar_imagenes_desde_json(pipeline, json_path: str | Path, output_root: str = "output"):
    json_path = Path(json_path)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("Iniciando generación de imágenes...\n")
    cancelado = False

    for i, bloque in enumerate(data, 1):
        if should_cancel():
            print("⛔ Cancelado por el usuario antes de procesar el siguiente bloque de imágenes.")
            cancelado = True
            break

        tipo = bloque["tipo"]
        referencia = bloque.get("referencia", "")

        print("=" * 50)
        print(f"Bloque {i}/{len(data)}: {tipo} - {referencia}")
        print("=" * 50 + "\n")

        if tipo in ["HISTORIA", "CURIOSIDAD"]:
            frames = bloque["secuencia_visual"]
            carpeta = Path(output_root) / tipo

            for frame_name, prompt in frames.items():
                if should_cancel():
                    print("⛔ Cancelado por el usuario durante generación de frames.")
                    cancelado = True
                    break

                generar_imagen(pipeline, prompt, carpeta, f"{frame_name}.png")

            if cancelado:
                break

        elif tipo == "ORACION":
            if should_cancel():
                print("⛔ Cancelado por el usuario antes de generar imagen de ORACION.")
                cancelado = True
                break

            carpeta = Path(output_root) / "ORACION"
            # Evita overwrite si hubiera varias ORACION:
            nombre = f"oracion_{i}.png"
            generar_imagen(pipeline, bloque["prompt_imagen"], carpeta, nombre)

    print("\n" + "=" * 50)
    if cancelado:
        print("PROCESO DE IMÁGENES INTERRUMPIDO POR CANCELACIÓN")
    else:
        print("TODAS LAS IMÁGENES GENERADAS")
    print("=" * 50)
