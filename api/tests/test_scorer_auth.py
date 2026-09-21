"""Service-to-service auth on Cloud Run, with the metadata server mocked."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from app.services import gcp  # noqa: E402
from pipeline import submission  # noqa: E402


@pytest.mark.asyncio
async def test_id_token_asks_the_metadata_server_for_the_audience():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["flavor"] = request.headers.get("Metadata-Flavor")
        return httpx.Response(200, text="id-token-123\n")

    token = await gcp.id_token("https://sdoc-scorer.example", transport=httpx.MockTransport(handler))

    assert token == "id-token-123"
    assert seen["url"].startswith(gcp.METADATA_URL + "/identity?audience=")
    assert "sdoc-scorer.example" in seen["url"]
    assert seen["flavor"] == "Google"


@pytest.mark.asyncio
async def test_access_token_reads_the_json_token():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "ya29.x", "expires_in": 3599}))
    assert await gcp.access_token(transport=transport) == "ya29.x"


@pytest.mark.asyncio
async def test_metadata_errors_surface():
    with pytest.raises(httpx.HTTPStatusError):
        await gcp.access_token(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


@pytest.mark.asyncio
async def test_no_auth_header_for_a_local_scorer():
    assert await submission.scorer_headers() == {}


@pytest.mark.asyncio
async def test_private_scorer_gets_an_id_token_for_its_own_url(monkeypatch):
    monkeypatch.setattr(settings, "scorer_auth", "gcp-id-token")
    monkeypatch.setattr(settings, "scorer_url", "https://sdoc-scorer-1.asia-southeast1.run.app")
    fetch = AsyncMock(return_value="tok")
    monkeypatch.setattr(submission.gcp, "id_token", fetch)

    assert await submission.scorer_headers() == {"Authorization": "Bearer tok"}
    fetch.assert_awaited_once_with("https://sdoc-scorer-1.asia-southeast1.run.app")
