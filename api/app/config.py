import os

from dotenv import load_dotenv

load_dotenv()  # walks up to repo root .env

NEON_DB_URI = os.environ.get("NEON_DB_URI", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TEXT_MODEL = os.environ.get("TEXT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
VISION_MODEL = os.environ.get("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")

DATA_DIR = os.environ.get("DATA_DIR", "data")
SCORER_URL = os.environ.get("SCORER_URL", "http://localhost:8080")
