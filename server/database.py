"""SQLite WAL engine, session maker, and database initialization."""

from __future__ import annotations

from pathlib import Path
from sqlalchemy import event, text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from shared.config import DB_PATH, DATA_DIR, DEFAULT_COURSE_ID, DEFAULT_COURSE_CODE, DEFAULT_COURSE_TITLE
from server.models import Base, Course


def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    """Set SQLite pragmas for WAL mode and concurrency."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


def get_engine(db_path: Path | None = None):
    """Create and return a SQLAlchemy engine for SQLite."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def get_session_maker(engine=None) -> sessionmaker:
    """Return a sessionmaker bound to the given (or default) engine."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine=None) -> sessionmaker:
    """Create all tables and seed the default course. Returns sessionmaker."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(bind=engine)

    SessionLocal = get_session_maker(engine)
    with SessionLocal() as session:
        existing = session.get(Course, DEFAULT_COURSE_ID)
        if not existing:
            default_course = Course(
                id=DEFAULT_COURSE_ID,
                code=DEFAULT_COURSE_CODE,
                title=DEFAULT_COURSE_TITLE,
                created_by=None,
            )
            session.add(default_course)
            session.commit()

    return SessionLocal


# Global session maker (initialized lazily)
_session_maker: sessionmaker | None = None


def get_db() -> Session:
    """FastAPI dependency: yield a DB session."""
    global _session_maker
    if _session_maker is None:
        _session_maker = init_db()
    session = _session_maker()
    try:
        yield session
    finally:
        session.close()


def set_session_maker(sm: sessionmaker):
    """Override the global session maker (for testing)."""
    global _session_maker
    _session_maker = sm
