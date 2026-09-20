"""Fallback-chain and cache behaviour of the OpenRouter client.

No network: the underlying completion call is replaced everywhere, so these
also assert that we never reach the API when a cached answer exists.

    uv run pytest api/tests/test_llm.py -v
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.config import _chain, settings  # noqa: E402
from app.services import llm  # noqa: E402


def reply(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture(autouse=True)
def configured_key(monkeypatch):
    """Every test here stubs the completion call, but the chain still checks
    that a key exists before it starts."""
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "enable_llm_cache", True)
    return tmp_path


def test_chain_keeps_primary_first_and_drops_duplicates():
    assert _chain("a", "b, a ,c") == ["a", "b", "c"]
    assert _chain("a", "") == ["a"]
    assert _chain("", " , ") == []


def test_chat_moves_to_the_next_model_when_one_is_dead(monkeypatch):
    seen = []

    def fake(messages, model, max_tokens):
        seen.append(model)
        if model == "dead":
            raise RuntimeError("404 no such model")
        return reply("{}")

    monkeypatch.setattr(llm, "_complete", fake)
    _, used = llm._chat([], ["dead", "alive"], 10)
    assert used == "alive"
    assert seen == ["dead", "alive"]


def test_chat_raises_once_the_whole_chain_is_exhausted(monkeypatch):
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    with pytest.raises(RuntimeError, match="429"):
        llm._chat([], ["one", "two"], 10)


def test_identical_requests_only_hit_the_api_once(cache, monkeypatch):
    calls = []

    def fake(messages, model, max_tokens):
        calls.append(model)
        return reply('{"shipper": "ACME"}')

    monkeypatch.setattr(llm, "_complete", fake)
    msgs = [{"role": "user", "content": "read this"}]
    first = llm.llm_json(msgs, model="m")
    second = llm.llm_json(msgs, model="m")

    assert first == second == {"shipper": "ACME"}
    assert calls == ["m"]


def test_a_different_document_is_a_cache_miss(cache, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_complete", lambda m, model, t: (calls.append(model), reply("{}"))[1])

    llm.llm_json([{"role": "user", "content": "doc one"}], model="m")
    llm.llm_json([{"role": "user", "content": "doc two"}], model="m")
    assert len(calls) == 2


def test_corrupt_cache_entry_is_treated_as_a_miss(cache, monkeypatch):
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: reply('{"ok": true}'))
    msgs = [{"role": "user", "content": "x"}]
    llm.llm_json(msgs, model="m")

    entry = next(cache.glob("*.json"))
    entry.write_text("not json{")
    assert llm.llm_json(msgs, model="m") == {"ok": True}
    assert json.loads(entry.read_text())["value"] == {"ok": True}


def test_cache_can_be_switched_off(cache, monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_cache", False)
    calls = []
    monkeypatch.setattr(llm, "_complete", lambda m, model, t: (calls.append(model), reply("{}"))[1])

    msgs = [{"role": "user", "content": "x"}]
    llm.llm_json(msgs, model="m")
    llm.llm_json(msgs, model="m")
    assert len(calls) == 2
    assert not list(cache.glob("*.json"))


def test_unparseable_reply_is_repaired_on_the_same_model(cache, monkeypatch):
    seen = []

    def fake(messages, model, max_tokens):
        seen.append(model)
        return reply("here you go:" if len(seen) == 1 else '{"consignee": "B"}')

    monkeypatch.setattr(llm, "_complete", fake)
    assert llm.llm_json([{"role": "user", "content": "x"}], model="m") == {"consignee": "B"}
    assert seen == ["m", "m"]


def test_a_missing_key_degrades_instead_of_crashing_on_import(monkeypatch):
    """The deterministic pipeline runs with no OpenRouter key at all, so the
    client must not be built until something actually calls a model."""
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm.get_client()

    from pipeline.extract import extract_fields_llm

    assert extract_fields_llm("SHIPPING INSTRUCTION") is None
