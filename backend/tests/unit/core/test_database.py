from app.core.database import engine


def test_db_pool_settings():
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 1800
