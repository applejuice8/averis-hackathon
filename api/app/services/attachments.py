"""Attachment storage + text previews, scoped to the owning email's data dir."""
import re
from pathlib import Path

from fastapi import HTTPException
from pipeline.extract import detect_doc_type, extract_fields
from pipeline.readers import read_attachment

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def save_attachments(data_dir: str, email_id: str,
                     files: list[tuple[str, bytes]]) -> list[str]:
    """Persist uploaded documents under data_dir/attachments/ and return the
    relative paths to store on the email record. Filenames carry no SI/BL
    signal — the pipeline pairs documents by detected content type."""
    rel_paths: list[str] = []
    for filename, data in files:
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, f"{filename} exceeds the 10 MB limit")
        name = _UNSAFE_NAME.sub("_", Path(filename).name).strip("._") or "file"
        rel = f"attachments/{email_id}_{name}"
        for i in range(2, 100):  # same-name uploads must not overwrite
            if rel not in rel_paths:
                break
            stem, dot, ext = name.partition(".")
            rel = f"attachments/{email_id}_{stem}_{i}{dot}{ext}" if dot else f"attachments/{email_id}_{name}_{i}"
        dest = Path(data_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        rel_paths.append(rel)
    return rel_paths


def preview_attachment(data_dir: str, attachments: list[str], index: int) -> dict:
    if index < 0 or index >= len(attachments):
        raise HTTPException(404, "No such attachment")
    root = Path(data_dir).resolve()
    path = (root / attachments[index]).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404, "Attachment is outside the data directory")
    if path.is_file() and path.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "Attachment exceeds the 10 MB preview limit")
    doc = read_attachment(path)
    extraction = extract_fields(doc.text) if doc.readable and doc.text else {"fields": {}}
    return {"name": path.name, "text": doc.text[:50000], "readable": doc.readable,
            "truncated": len(doc.text) > 50000, "error": doc.meta.get("error"),
            "doc_type": detect_doc_type(doc.text) if doc.readable and doc.text else None,
            "fields": extraction["fields"]}
