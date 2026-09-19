"""Engine, session factory and Base — the only place SQLAlchemy is wired."""
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..core.config import settings


def _asyncpg_uri(uri: str) -> tuple[str, dict]:
    """Normalise a Neon postgres URI for asyncpg: switch driver scheme, drop
    params asyncpg doesn't understand (sslmode, channel_binding), and return
    connect_args that enforce TLS instead."""
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    parts = urlsplit(uri)
    query = dict(parse_qsl(parts.query))
    query.pop("sslmode", None)
    query.pop("channel_binding", None)
    clean = urlunsplit(
        ("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), "")
    )
    ctx = ssl.create_default_context()
    return clean, {"ssl": ctx}


class Base(DeclarativeBase):
    pass


if settings.neon_db_uri:
    _uri, _connect_args = _asyncpg_uri(settings.neon_db_uri)
    engine = create_async_engine(_uri, connect_args=_connect_args, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
else:
    engine = None
    SessionLocal = None


async def init_db():
    if engine is None:
        return
    from . import models  # noqa: F401 - register tables

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
