import os

from dotenv import load_dotenv

load_dotenv()  # walks up to repo root .env

NEON_DB_URI = os.environ.get("NEON_DB_URI", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TEXT_MODEL = os.environ.get("TEXT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
VISION_MODEL = os.environ.get("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_data = os.environ.get("DATA_DIR", "data")
DATA_DIR = _data if os.path.isabs(_data) else os.path.join(REPO_ROOT, _data)

SCORER_URL = os.environ.get("SCORER_URL", "http://localhost:8080")
