"""Application settings — single source of truth for env configuration.

Reads from the repo-root `.env` and process environment. All modules consume
the `settings` singleton; nothing else touches os.environ directly.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# api/app/core/config.py -> repo root is three package levels up
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", extra="ignore"
    )

    # external services
    neon_db_uri: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    scorer_url: str = "http://localhost:8080"

    # models
    text_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    vision_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

    # data + LLM assist switches (off => deterministic scoring runs)
    data_dir: str = "data"
    enable_llm_classify: bool = False
    enable_llm_fill: bool = False
    enable_vision_ocr: bool = False

    @property
    def resolved_data_dir(self) -> str:
        """Relative DATA_DIR anchors at the repo root, not the cwd."""
        if os.path.isabs(self.data_dir):
            return self.data_dir
        return str(REPO_ROOT / self.data_dir)


settings = Settings()
