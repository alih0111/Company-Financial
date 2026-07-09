from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from codal_ingestor.config import get_settings
from codal_ingestor.models import Base


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_schema_ready = False


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    Base.metadata.create_all(bind=get_engine())
    _schema_ready = True


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    if get_settings().auto_create_schema:
        ensure_schema()

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
