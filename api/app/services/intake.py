"""Live intake: validate an uploaded email + attachments and store them
where the pipeline readers already look (DATA_DIR/uploads/<email_id>/)."""
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

MAX_FILES = 4
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
MAX_SENDER = 200
MAX_SUBJECT = 300
MAX_BODY = 20_000
MAX_NAME = 80
ALLOWED_SUFFIXES = {".txt", ".pdf", ".docx", ".xlsx"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class IntakeError(ValueError):
    """Invalid submission; the message is shown to the user as-is."""


@dataclass(frozen=True)
class IntakeFile:
    name: str
    data: bytes


def safe_filename(raw: str, taken: set[str]) -> str:
    """Basename only, [A-Za-z0-9._-], at most 80 chars, lower-case extension,
    unique within one submission."""
    base = PurePosixPath(raw.replace("\\", "/")).name
    cleaned = _UNSAFE.sub("_", base).strip("._") or "attachment"
    suffix = PurePosixPath(cleaned).suffix.lower()
    stem = cleaned[: len(cleaned) - len(suffix)] if suffix else cleaned
    stem = stem[: MAX_NAME - len(suffix)]
    name = f"{stem}{suffix}"
    n = 2
    while name.lower() in taken:
        name = f"{stem[: MAX_NAME - len(suffix) - 3]}-{n}{suffix}"
        n += 1
    taken.add(name.lower())
    return name


def check_content(name: str, data: bytes) -> None:
    """The bytes must match the extension (no renamed executables)."""
    suffix = PurePosixPath(name).suffix
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise IntakeError(f"{name} is not a PDF file.")
    if suffix in {".docx", ".xlsx"} and not data.startswith(b"PK\x03\x04"):
        raise IntakeError(f"{name} is not a valid {suffix[1:]} file.")
    if suffix == ".txt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise IntakeError(f"{name} is not UTF-8 text.") from None


def validate_submission(sender: str, subject: str, body: str,
                        uploads: list[tuple[str, bytes]]) -> list[IntakeFile]:
    if not sender.strip() or len(sender) > MAX_SENDER:
        raise IntakeError(f"Enter a sender address (up to {MAX_SENDER} characters).")
    if not subject.strip() or len(subject) > MAX_SUBJECT:
        raise IntakeError(f"Enter a subject (up to {MAX_SUBJECT} characters).")
    if len(body) > MAX_BODY:
        raise IntakeError(f"The body is limited to {MAX_BODY:,} characters.")
    if len(uploads) > MAX_FILES:
        raise IntakeError(f"Attach at most {MAX_FILES} files.")
    taken: set[str] = set()
    files: list[IntakeFile] = []
    total = 0
    for raw_name, data in uploads:
        name = safe_filename(raw_name, taken)
        if len(data) > MAX_FILE_BYTES:
            raise IntakeError(f"{name} is larger than 3 MiB.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise IntakeError("Attachments are limited to 3 MiB in total.")
        if PurePosixPath(name).suffix not in ALLOWED_SUFFIXES:
            raise IntakeError(f"{name} is not allowed: use .txt, .pdf, .docx or .xlsx.")
        check_content(name, data)
        files.append(IntakeFile(name, data))
    return files


def new_email_id(now: datetime | None = None, token: str | None = None) -> str:
    return f"upload_{(now or datetime.now(UTC)):%Y%m%d}_{token or secrets.token_hex(3)}"


def save_files(data_dir: Path, subdir: str, email_id: str, files: list[IntakeFile]) -> list[str]:
    """Write each file once (Cloud Storage FUSE has no atomic rename) and
    return paths relative to DATA_DIR, the form the pipeline readers use."""
    folder = Path(data_dir) / subdir / email_id
    folder.mkdir(parents=True, exist_ok=False)
    paths = []
    for f in files:
        (folder / f.name).write_bytes(f.data)
        paths.append(f"{subdir}/{email_id}/{f.name}")
    return paths


def build_record(email_id: str, sender: str, subject: str, body: str, attachments: list[str]) -> dict:
    """Same shape as an inbox JSON record."""
    return {"email_id": email_id, "from": sender, "subject": subject, "body": body, "attachments": attachments}
