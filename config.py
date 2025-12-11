# config.py
import os
from pathlib import Path
from dotenv import load_dotenv
from mistralai import Mistral
from elevenlabs.client import ElevenLabs

load_dotenv()

API_KEY_MISTRAL = os.getenv("MISTRAL_API_KEY")
API_KEY_ELEVENLABS = os.getenv("ELEVEN_LABS_API_KEY")

if not API_KEY_MISTRAL:
    raise RuntimeError("MISTRAL_API_KEY no está definido en el .env")

if not API_KEY_ELEVENLABS:
    raise RuntimeError("ELEVEN_LABS_API_KEY no está definido en el .env")

client_mistral = Mistral(api_key=API_KEY_MISTRAL)
client_eleven = ElevenLabs(api_key=API_KEY_ELEVENLABS)

# Rutas base que usas en todo el proyecto
BASE_DIR = Path(__file__).resolve().parent
BIBLE_JSON_PATH = Path(r"D:\\Video_bib_pipeline\\biblia_completa_rv1960.json")
ZIMAGE_GGUF = Path(r"D:\\Video_bib_pipeline\\z_image_turbo-Q8_0.gguf")
