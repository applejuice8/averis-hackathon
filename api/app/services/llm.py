"""OpenRouter client: model fallback chain + content-hash response cache.

Two things bite when the assists run on free-tier models: slugs get retired
without notice, and the shared key runs out of quota. So every call walks a
chain of models — a model that keeps failing is skipped, not fatal — and
every parsed response is cached by the hash of its request, which makes a
rerun over the same document free.
"""
import base64
import hashlib
import json
import re
from pathlib import Path

from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import settings

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Built on first use, not on import: the deterministic pipeline runs
    without a key at all, and the SDK refuses to construct without one."""
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set - AI assists are unavailable")
        _client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            default_headers={"X-Title": "DockerOps"},
        )
    return _client

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json_block(raw: str):
    """Defensive JSON extraction: strip code fences and any prose around the
    object — free/community models don't guarantee structured outputs."""
    raw = raw.strip()
    m = _FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


# --- cache ---------------------------------------------------------------

def _cache_key(kind: str, models: list[str], messages, max_tokens: int) -> str:
    blob = json.dumps(
        {"kind": kind, "models": models, "messages": messages, "max_tokens": max_tokens},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return Path(settings.resolved_llm_cache_dir) / f"{key}.json"


def cache_read(key: str):
    """Cached value, or None on a miss. A damaged cache file is a miss."""
    if not settings.enable_llm_cache:
        return None
    try:
        return json.loads(_cache_path(key).read_text())["value"]
    except (OSError, ValueError, KeyError):
        return None


def cache_write(key: str, model: str, value) -> None:
    """Best effort — a cache we can't write to must never fail a run."""
    if not settings.enable_llm_cache:
        return
    try:
        path = _cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"model": model, "value": value}))
    except (OSError, TypeError, ValueError):
        pass


# --- calls ---------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def _complete(messages, model, max_tokens):
    return get_client().chat.completions.create(
        model=model, messages=messages, temperature=0, max_tokens=max_tokens
    )


def _chat(messages, models: list[str], max_tokens: int):
    """-> (response, model that answered). Walks the chain; raises the last
    error only once every model in it has failed its own retries."""
    get_client()  # fail fast on a missing key rather than retrying nothing
    last = None
    for model in models:
        try:
            return _complete(messages, model, max_tokens), model
        except Exception as e:  # dead slug, rate limit, timeout
            last = e
    raise last or RuntimeError("no model configured")


def llm_json(messages, model=None, max_tokens=2000):
    """Chat call that returns a parsed JSON object. One repair retry if the
    first response doesn't parse."""
    models = [model] if model else settings.text_model_chain
    key = _cache_key("text", models, messages, max_tokens)
    hit = cache_read(key)
    if hit is not None:
        return hit

    resp, used = _chat(messages, models, max_tokens)
    raw = resp.choices[0].message.content or ""
    try:
        out = extract_json_block(raw)
    except json.JSONDecodeError:
        repair = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "That was not valid JSON. Reply with ONLY the corrected JSON object."},
        ]
        # stay on the model that answered — switching now would cost a
        # second cold call for what is usually a formatting slip
        resp, used = _chat(repair, [used], max_tokens)
        out = extract_json_block(resp.choices[0].message.content or "")

    cache_write(key, used, out)
    return out


def vision_json(prompt: str, image_png: bytes, model=None, max_tokens=2000):
    """Send one rendered page image to the vision model; parse JSON back."""
    b64 = base64.b64encode(image_png).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]
    models = [model] if model else settings.vision_model_chain
    key = _cache_key("vision", models, messages, max_tokens)
    hit = cache_read(key)
    if hit is not None:
        return hit

    resp, used = _chat(messages, models, max_tokens)
    out = extract_json_block(resp.choices[0].message.content or "")
    cache_write(key, used, out)
    return out
