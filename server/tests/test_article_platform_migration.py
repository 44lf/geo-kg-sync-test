from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import server.app.modules.articles.models  # noqa: F401
import server.app.modules.collector.models  # noqa: F401
from alembic import command
from server.app.core.config import get_settings
from server.tests.utils import get_test_database_url, reset_test_database

PARENT_REVISION = "0073_collector_gateway_model"
CURRENT_REVISION = "0074_article_platform_context"


def _new_temp_data_dir() -> Path:
    return Path(tempfile.gettempdir()) / "geo-test-data" / uuid.uuid4().hex


def _column_names(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _create_isolated_test_database(base_database_url: str) -> str:
    url = make_url(base_database_url)
    base_database_name = url.database
    if not base_database_name or "test" not in base_database_name.lower():
        raise RuntimeError("Refusing to create an isolated database from a non-test URL")
    database_name = f"{base_database_name}_provenance_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(url.set(database=None), pool_pre_ping=True)
    try:
        escaped_name = database_name.replace("`", "``")
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE `{escaped_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        admin_engine.dispose()
    return url.set(database=database_name).render_as_string(hide_password=False)


def _drop_isolated_test_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database
    if (
        not database_name
        or "test" not in database_name.lower()
        or "_provenance_" not in database_name
    ):
        raise RuntimeError("Refusing to drop a database outside this isolated migration test")
    admin_engine = create_engine(url.set(database=None), pool_pre_ping=True)
    try:
        escaped_name = database_name.replace("`", "``")
        with admin_engine.begin() as connection:
            connection.execute(text(f"DROP DATABASE `{escaped_name}`"))
    finally:
        admin_engine.dispose()


@pytest.mark.mysql
def test_article_platform_migration_upgrade_downgrade_upgrade_preserves_legacy_null(
    monkeypatch,
):
    data_dir = _new_temp_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = _create_isolated_test_database(get_test_database_url())
    engine = create_engine(database_url, pool_pre_ping=True)
    reset_test_database(engine, create_schema=False)
    monkeypatch.setenv("GEO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("GEO_DATABASE_URL", database_url)
    get_settings.cache_clear()

    try:
        cfg = AlembicConfig("alembic.ini")
        command.upgrade(cfg, PARENT_REVISION)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users
                        (id, username, password_hash, role, is_active,
                         must_change_password, solo_mode, created_at)
                    VALUES
                        (99174, 'migration-provenance-user', 'not-used',
                         'operator', 1, 0, 0, CURRENT_TIMESTAMP)
                    """
                )
            )
            result = connection.execute(
                text(
                    """
                    INSERT INTO articles
                        (user_id, title, content_json, content_html, plain_text,
                         word_count, status, review_status, version, ai_checking,
                         is_deleted, created_at, updated_at)
                    VALUES
                        (99174, 'legacy article', '{}', '', '', 0, 'draft',
                         'approved', 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
            )
            legacy_article_id = result.lastrowid

        command.upgrade(cfg, CURRENT_REVISION)

        assert "target_platform_code" in _column_names(engine, "articles")
        assert "article_generation_contexts" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        """
                        SELECT target_platform_code
                        FROM articles
                        WHERE id = :article_id
                        """
                    ),
                    {"article_id": legacy_article_id},
                )
                is None
            )

        command.downgrade(cfg, PARENT_REVISION)
        assert "target_platform_code" not in _column_names(engine, "articles")
        assert "article_generation_contexts" not in inspect(engine).get_table_names()

        command.upgrade(cfg, CURRENT_REVISION)
        assert "target_platform_code" in _column_names(engine, "articles")
        assert "article_generation_contexts" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        """
                        SELECT target_platform_code
                        FROM articles
                        WHERE id = :article_id
                        """
                    ),
                    {"article_id": legacy_article_id},
                )
                is None
            )
    finally:
        engine.dispose()
        _drop_isolated_test_database(database_url)
        shutil.rmtree(data_dir, ignore_errors=True)
        get_settings.cache_clear()
