from __future__ import annotations

from app.core.config import Settings

_WENGU_KEYS = (
    "WENGU_ENV",
    "WENGU_DATA_DIR",
    "WENGU_DB_PATH",
    "WENGU_INBOX_DIR",
    "WENGU_SEEDS_DIR",
    "WENGU_LOG_LEVEL",
)


def _clear_env(monkeypatch) -> None:
    for key in _WENGU_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_read_env_file(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WENGU_ENV=prod\nWENGU_DB_PATH=./custom/wengu.db\nWENGU_LOG_LEVEL=debug\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.env == "prod"
    assert settings.log_level == "debug"
    assert settings.db_path is not None
    assert settings.db_path.is_absolute()
    assert settings.db_path.parent.name == "custom"
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert settings.database_url.endswith("custom/wengu.db")


def test_inbox_path_defaults_under_data_dir(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    settings = Settings(_env_file=None, data_dir=tmp_path)

    assert settings.inbox_path == tmp_path / "inbox"
    assert settings.db_path == tmp_path / "wengu.db"

    overridden = Settings(
        _env_file=None,
        data_dir=tmp_path,
        inbox_dir=tmp_path / "drop",
    )
    assert overridden.inbox_path == tmp_path / "drop"
