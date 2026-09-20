"""Direct access to the spam model — the same detector the pipeline's
classify stage consults, exposed for demos and evaluation."""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.spam import predict_spam  # noqa: E402

from ...schemas.spam import SpamDetectRequest, SpamDetectResponse  # noqa: E402

router = APIRouter()


@router.post("/spam/detect", response_model=SpamDetectResponse)
async def detect_spam(req: SpamDetectRequest):
    record = {
        "from": req.sender,
        "subject": req.subject,
        "body": req.body,
        "attachments": req.attachments,
    }
    verdict = await run_in_threadpool(predict_spam, record)
    if verdict is None:
        raise HTTPException(
            503, "spam model not loaded — train it first (api/ml/train.py)"
        )
    return SpamDetectResponse(spam=verdict.spam, score=verdict.score)
