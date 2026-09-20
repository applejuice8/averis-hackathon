"""Top-level API router — routes are thin HTTP adapters over
repositories/services; no SQL or business logic lives here."""
from fastapi import APIRouter

from .routes import auth, emails, intake, pipeline, review

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(emails.router)
api_router.include_router(intake.router)
api_router.include_router(pipeline.router)
api_router.include_router(review.router)
