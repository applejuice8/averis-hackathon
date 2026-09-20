"""Google metadata-server tokens for service-to-service calls on Cloud Run.

No SDK needed: two GETs against the metadata server, which only exists
inside Google Cloud (tests inject an httpx transport).
"""
import httpx

METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
_HEADERS = {"Metadata-Flavor": "Google"}


async def access_token(transport: httpx.AsyncBaseTransport | None = None) -> str:
    """OAuth token for Google APIs (e.g. starting a Cloud Run Job)."""
    async with httpx.AsyncClient(transport=transport, timeout=5) as c:
        r = await c.get(f"{METADATA_URL}/token", headers=_HEADERS)
        r.raise_for_status()
        return r.json()["access_token"]


async def id_token(audience: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """OIDC identity token for calling an IAM-private Cloud Run service."""
    async with httpx.AsyncClient(transport=transport, timeout=5) as c:
        r = await c.get(f"{METADATA_URL}/identity", params={"audience": audience}, headers=_HEADERS)
        r.raise_for_status()
        return r.text.strip()
