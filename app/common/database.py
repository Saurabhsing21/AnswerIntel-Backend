from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.common.config import settings


# pre_ping: Neon suspends idle computes, which drops pooled connections; test each one before use.
engine = create_engine(settings.database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass