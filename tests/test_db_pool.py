from app.common.config import settings
from app.common.database import engine


def test_engine_pool_uses_settings():
    assert engine.pool.size() == settings.db_pool_size
    assert engine.pool._max_overflow == settings.db_max_overflow
    assert engine.pool._timeout == settings.db_pool_timeout_seconds
    assert settings.db_pool_size >= 4 * (1 + settings.scan_concurrency)
