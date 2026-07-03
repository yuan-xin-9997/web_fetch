from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_up_and_down(tmp_path) -> None:
    database_path = (tmp_path / "migration.db").as_posix()
    async_url = f"sqlite+aiosqlite:///{database_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", async_url)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    assert {"jobs", "job_items"}.issubset(inspect(engine).get_table_names())
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database_path}")
    assert "jobs" not in inspect(engine).get_table_names()
    engine.dispose()
