"""Top-level API router — routes are thin HTTP adapters over
repositories/services; no SQL or business logic lives here."""
from fastapi import APIRouter

from .routes import calendar, emails, gmail, intake, pipeline, review, spam

api_router = APIRouter(prefix="/api")
api_router.include_router(emails.router)
api_router.include_router(intake.router)
api_router.include_router(pipeline.router)
api_router.include_router(review.router)
api_router.include_router(calendar.router)
api_router.include_router(gmail.router)
api_router.include_router(spam.router)
