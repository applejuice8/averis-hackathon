"""Load the SDOC bundle inbox into Postgres.

Reads DATA_DIR/inbox/email_*.json (same layout as the provided bundle or the
docker scorer's /data mount) and upserts into the `emails` table.

    uv run python -m pipeline.ingest
"""
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import DATA_DIR  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Email  # noqa: E402


async def ingest(data_dir: str = DATA_DIR) -> int:
    inbox = Path(data_dir) / "inbox"
    records = [
        json.loads(p.read_text())
        for p in sorted(inbox.glob("email_*.json"))
    ]
    async with SessionLocal() as s:
        for rec in records:
            stmt = insert(Email).values(
                email_id=rec["email_id"],
                sender=rec.get("from", ""),
                subject=rec.get("subject", ""),
                body=rec.get("body", ""),
                attachments=rec.get("attachments", []),
            ).on_conflict_do_update(
                index_elements=["email_id"],
                set_={"sender": rec.get("from", ""), "subject": rec.get("subject", ""),
                      "body": rec.get("body", ""), "attachments": rec.get("attachments", [])},
            )
            await s.execute(stmt)
        await s.commit()
    return len(records)


if __name__ == "__main__":
    n = asyncio.run(ingest(sys.argv[1] if len(sys.argv) > 1 else DATA_DIR))
    print(f"ingested {n} emails")
