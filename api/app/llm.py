import json
import re

from openai import OpenAI

from . import config

client = OpenAI(
    base_url=config.OPENROUTER_BASE_URL,
    api_key=config.OPENROUTER_API_KEY,
    default_headers={"X-Title": "SDOC Verifier"},
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json_block(raw: str):
    raw = raw.strip()
    m = _FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def llm_json(messages, model=None, max_tokens=2000):
    resp = client.chat.completions.create(
        model=model or config.TEXT_MODEL,
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
    )
    return extract_json_block(resp.choices[0].message.content or "")
