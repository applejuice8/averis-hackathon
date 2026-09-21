from fastapi import APIRouter, Depends, Response

from ..deps import require_reviewer

router = APIRouter()


@router.get("/auth/check", status_code=204, dependencies=[Depends(require_reviewer)])
async def check_passcode() -> Response:
    """204 when the caller may write, 401 otherwise. The web app uses it to
    decide whether reviewer mode is unlocked."""
    return Response(status_code=204)
