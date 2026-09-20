import sys
from pathlib import Path

import joblib
import pytest

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from ml.model import SpamDetector, build_pipeline, format_email, save_detector  # noqa: E402
from ml.train import DEFAULT_DATA_DIR, dataset_fingerprint, load_training_data  # noqa: E402


def test_training_dataset_is_deduplicated_and_reproducible():
    texts, labels = load_training_data(DEFAULT_DATA_DIR)

    assert len(texts) == 519
    assert sum(labels) == 39
    assert dataset_fingerprint(texts, labels) == "751f5802ee4a82ba733ace311552597d757873d22951325aabc98db551b038fe"


def test_detector_round_trip(tmp_path):
    texts = [
        format_email(subject="shipping update", body="documents are ready"),
        format_email(subject="shipping update", body="documents are complete"),
        format_email(subject="claim prize", body="click now to win"),
        format_email(subject="claim prize", body="click now to collect"),
    ]
    pipeline = build_pipeline().fit(texts, [0, 0, 1, 1])
    artifact_path = save_detector(pipeline, 0.4, {"model_name": "test"}, tmp_path / "spam.joblib")

    detector = SpamDetector.load(artifact_path)

    assert detector.threshold == 0.4
    assert detector.metadata == {"model_name": "test"}
    assert detector.score(texts[2]) > detector.score(texts[0])


@pytest.mark.parametrize(
    "artifact",
    [
        {},
        {"format_version": 999},
        {"format_version": 1, "pipeline": "bad", "threshold": 0.5, "metadata": {}},
    ],
)
def test_invalid_artifact_is_rejected(tmp_path, artifact):
    path = tmp_path / "invalid.joblib"
    joblib.dump(artifact, path)

    with pytest.raises(ValueError, match="spam model artifact"):
        SpamDetector.load(path)


def test_packaged_detector_matches_selected_model():
    detector = SpamDetector.load(API_DIR / "ml/models/spam.joblib")
    spam = format_email(
        sender="info@crypto-invest.net",
        subject="Increase your shipping revenue with this ONE weird trick",
        body="Congratulations! You have won. Claim now.",
    )
    legitimate = format_email(
        sender="ops@example.com",
        subject="Shipping documents ready",
        body="The draft bill of lading is attached for review.",
    )

    assert detector.metadata["model_name"] == "word_tfidf_logistic"
    assert detector.metadata["dataset_sha256"] == "751f5802ee4a82ba733ace311552597d757873d22951325aabc98db551b038fe"
    assert detector.score(spam) >= detector.threshold
    assert detector.score(legitimate) < detector.threshold
