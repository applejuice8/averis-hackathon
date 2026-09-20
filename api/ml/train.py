"""Train the selected spam model on the labeled Averis email dataset."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import sklearn

from .model import MODEL_NAME, build_pipeline, format_email, save_detector

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "docs-provided/problem-statement/sdoc-hackathon-docker/data_v2"
DEFAULT_OUTPUT = Path(__file__).parent / "models/spam.joblib"
DEFAULT_THRESHOLD = 0.255


def ground_truth_path(data_dir: Path) -> Path | None:
    """The answer key, wherever it lives.

    It used to sit beside the eval data, but it is deliberately kept out of the
    public repo (see secrets/README.md), so fall back to the ignored secrets/
    copy. Returns None when neither exists, which lets callers skip rather than
    crash on a fresh clone or in CI.
    """
    for candidate in (data_dir / "ground_truth.json", REPO_ROOT / "secrets/ground_truth.json"):
        if candidate.is_file():
            return candidate
    return None


def load_training_data(data_dir: Path) -> tuple[list[str], list[int]]:
    key = ground_truth_path(data_dir)
    if key is None:
        raise FileNotFoundError(
            "no ground_truth.json in "
            f"{data_dir} or {REPO_ROOT / 'secrets'} — see secrets/README.md"
        )
    labels = json.loads(key.read_text())
    records: dict[str, int] = {}
    for path in sorted((data_dir / "inbox").glob("*.json")):
        email = json.loads(path.read_text())
        text = format_email(
            sender=email.get("from", ""),
            subject=email.get("subject", ""),
            body=email.get("body", ""),
        )
        label = int(labels[email["email_id"]]["category"] == "SPAM")
        if text in records and records[text] != label:
            raise ValueError(f"conflicting labels for duplicate email {email['email_id']}")
        records[text] = label
    if len(records) < 2 or len(set(records.values())) != 2:
        raise ValueError("training data must contain unique spam and legitimate emails")
    return list(records), list(records.values())


def dataset_fingerprint(texts: list[str], labels: list[int]) -> str:
    digest = hashlib.sha256()
    for text, label in zip(texts, labels, strict=True):
        digest.update(str(label).encode())
        digest.update(b"\0")
        digest.update(text.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def train(data_dir: Path, output_path: Path) -> dict[str, object]:
    texts, labels = load_training_data(data_dir)
    pipeline = build_pipeline()
    pipeline.fit(texts, labels)
    metadata: dict[str, object] = {
        "model_name": MODEL_NAME,
        "trained_at": datetime.now(UTC).isoformat(),
        "training_records": len(texts),
        "spam_records": sum(labels),
        "dataset_sha256": dataset_fingerprint(texts, labels),
        "sklearn_version": sklearn.__version__,
    }
    save_detector(pipeline, DEFAULT_THRESHOLD, metadata, output_path)
    return {**metadata, "threshold": DEFAULT_THRESHOLD, "output_path": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(train(args.data_dir, args.output), indent=2))


if __name__ == "__main__":
    main()
