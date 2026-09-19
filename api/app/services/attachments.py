"""Text previews limited to the selected email's attachments."""
from pathlib import Path

from fastapi import HTTPException
from pipeline.extract import detect_doc_type, extract_fields
from pipeline.readers import read_attachment


def preview_attachment(data_dir: str, attachments: list[str], index: int) -> dict:
    if index < 0 or index >= len(attachments):
        raise HTTPException(404, "No such attachment")
    root = Path(data_dir).resolve()
    path = (root / attachments[index]).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404, "Attachment is outside the data directory")
    if path.is_file() and path.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(413, "Attachment exceeds the 10 MB preview limit")
    doc = read_attachment(path)
    extraction = extract_fields(doc.text) if doc.readable and doc.text else {"fields": {}}
    return {"name": path.name, "text": doc.text[:50000], "readable": doc.readable,
            "truncated": len(doc.text) > 50000, "error": doc.meta.get("error"),
            "doc_type": detect_doc_type(doc.text) if doc.readable and doc.text else None,
            "fields": extraction["fields"]}
