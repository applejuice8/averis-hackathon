"""Production spam-model definition and trusted artifact loading."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

ARTIFACT_FORMAT_VERSION = 1
MODEL_NAME = "word_tfidf_logistic"


def format_email(sender: str = "", subject: str = "", body: str = "") -> str:
    return f"From: {sender}\nSubject: {subject}\nBody: {body}"


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "vectorizer",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=2,
                    max_df=0.98,
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1_000,
                    random_state=42,
                ),
            ),
        ]
    )


@dataclass(frozen=True)
class SpamDetector:
    pipeline: Pipeline
    threshold: float
    metadata: dict[str, Any]

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "SpamDetector":
        artifact = joblib.load(path)
        if not isinstance(artifact, dict) or artifact.get("format_version") != ARTIFACT_FORMAT_VERSION:
            raise ValueError("unsupported spam model artifact")

        pipeline = artifact.get("pipeline")
        threshold = artifact.get("threshold")
        metadata = artifact.get("metadata")
        if not isinstance(pipeline, Pipeline) or not isinstance(metadata, dict):
            raise ValueError("invalid spam model artifact")
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("invalid spam model threshold")
        return cls(pipeline=pipeline, threshold=float(threshold), metadata=metadata)

    def score(self, text: str) -> float:
        return float(self.pipeline.predict_proba([text])[0, 1])


def save_detector(
    pipeline: Pipeline,
    threshold: float,
    metadata: dict[str, Any],
    output_path: str | os.PathLike[str],
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "format_version": ARTIFACT_FORMAT_VERSION,
        "pipeline": pipeline,
        "threshold": threshold,
        "metadata": metadata,
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".joblib", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        joblib.dump(artifact, temporary_path)
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return output
