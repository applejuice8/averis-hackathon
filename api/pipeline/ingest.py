"""Load the SDOC bundle inbox into Postgres.

Reads DATA_DIR/inbox/email_*.json (same layout as the provided bundle or the
docker scorer's /data mount) and upserts into the `emails` table.

    uv run python -m pipeline.ingest
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402


async def ingest(data_dir: str | None = None) -> int:
    inbox = Path(data_dir or settings.resolved_data_dir) / "inbox"
    records = [
        json.loads(p.read_text())
        for p in sorted(inbox.glob("email_*.json"))
    ]
    async with SessionLocal() as s:
        return await emails_repo.upsert_many(s, records)


if __name__ == "__main__":
    n = asyncio.run(ingest(sys.argv[1] if len(sys.argv) > 1 else None))
    print(f"ingested {n} emails")
