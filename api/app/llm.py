import base64
import json
import re

from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from . import config

client = OpenAI(
    base_url=config.OPENROUTER_BASE_URL,
    api_key=config.OPENROUTER_API_KEY,
    default_headers={"X-Title": "SDOC Verifier"},
)

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


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def _chat(messages, model, max_tokens):
    return client.chat.completions.create(
        model=model, messages=messages, temperature=0, max_tokens=max_tokens
    )


def llm_json(messages, model=None, max_tokens=2000):
    """Chat call that returns a parsed JSON object. One repair retry if the
    first response doesn't parse."""
    resp = _chat(messages, model or config.TEXT_MODEL, max_tokens)
    raw = resp.choices[0].message.content or ""
    try:
        return extract_json_block(raw)
    except json.JSONDecodeError:
        repair = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "That was not valid JSON. Reply with ONLY the corrected JSON object."},
        ]
        resp = _chat(repair, model or config.TEXT_MODEL, max_tokens)
        return extract_json_block(resp.choices[0].message.content or "")


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
    resp = _chat(messages, model or config.VISION_MODEL, max_tokens)
    return extract_json_block(resp.choices[0].message.content or "")
