"""Application settings — single source of truth for env configuration.

Reads from the repo-root `.env` and process environment. All modules consume
the `settings` singleton; nothing else touches os.environ directly.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# api/app/core/config.py -> repo root is three package levels up
REPO_ROOT = Path(__file__).resolve().parents[3]


def _chain(primary: str, fallbacks: str) -> list[str]:
    """Primary model first, then the fallbacks, de-duplicated."""
    out: list[str] = []
    for m in [primary, *fallbacks.split(",")]:
        m = m.strip()
        if m and m not in out:
            out.append(m)
    return out


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", extra="ignore"
    )

    # external services
    neon_db_uri: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    scorer_url: str = "http://localhost:8080"

    # models — the primary plus a comma-separated fallback chain. Free-tier
    # slugs get retired or rate-limited without notice; walking a chain keeps
    # the assists alive when one of them goes away mid-demo.
    text_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    text_model_fallbacks: str = (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,"
        "meta-llama/llama-3.3-70b-instruct:free"
    )
    vision_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    vision_model_fallbacks: str = ""

    # cache LLM responses by content hash so reruns cost nothing
    enable_llm_cache: bool = True
    llm_cache_dir: str = ".cache/llm"

    # data + LLM assist switches (off => deterministic scoring runs)
    data_dir: str = "data"
    enable_llm_classify: bool = False
    enable_llm_fill: bool = False
    enable_vision_ocr: bool = False

    # demo access: an empty passcode leaves writes open (local dev only)
    demo_passcode: str = ""
    cors_origins: str = "http://localhost:3000"

    # where full pipeline runs execute: "inline" (api process) or
    # "cloudrun-job" (a Cloud Run Job execution per run)
    run_executor: str = "inline"
    gcp_project_id: str = ""
    gcp_region: str = ""
    worker_job: str = "sdoc-worker"

    # spend guards: a published passcode must not be able to pile up billable runs
    max_active_runs: int = 1
    max_runs_per_day: int = 20

    # "gcp-id-token" when the scorer is an IAM-private Cloud Run service
    scorer_auth: str = "none"

    # live-intake files land in DATA_DIR/UPLOADS_SUBDIR/<email_id>/
    uploads_subdir: str = "uploads"
    log_format: str = "text"  # "json" => Cloud Logging structured lines

    @property
    def text_model_chain(self) -> list[str]:
        return _chain(self.text_model, self.text_model_fallbacks)

    @property
    def vision_model_chain(self) -> list[str]:
        return _chain(self.vision_model, self.vision_model_fallbacks)

    @property
    def resolved_llm_cache_dir(self) -> str:
        if os.path.isabs(self.llm_cache_dir):
            return self.llm_cache_dir
        return str(REPO_ROOT / self.llm_cache_dir)

    @property
    def resolved_data_dir(self) -> str:
        """Relative DATA_DIR anchors at the repo root, not the cwd."""
        if os.path.isabs(self.data_dir):
            return self.data_dir
        return str(REPO_ROOT / self.data_dir)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_root(self) -> Path:
        return Path(self.resolved_data_dir) / self.uploads_subdir


settings = Settings()
