from sqlalchemy import create_engine,text
from sqlalchemy.orm import DeclarativeBase

from app.common.config import settings


engine = create_engine(
    settings.database_url,
)


class Base(DeclarativeBase):
    pass

with engine.connect() as connection:
    result = connection.execute(text("SELECT 1"))
    print(result.scalar())