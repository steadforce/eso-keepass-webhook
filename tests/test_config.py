from pathlib import Path

import pytest

from eso_keepass_webhook.config import Config, ConfigError, SecretFile


def test_from_env_reads_token_file(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("from-file\n")
    config = Config.from_env(
        {"KDBX_PATH": "/db.kdbx", "KDBX_PASSWORD_FILE": "/pw", "AUTH_TOKEN_FILE": str(token_file)}
    )
    assert config.auth_token == "from-file"
    assert config.auth_token_file == token_file
    assert config.reload_interval == 10
    assert config.password_file == Path("/pw")
    assert config.port == 8080


@pytest.mark.parametrize(
    "env",
    [
        {"KDBX_PASSWORD": "pw", "AUTH_TOKEN": "t"},
        {"KDBX_PATH": "/db.kdbx", "AUTH_TOKEN": "t"},
        {"KDBX_PATH": "/db.kdbx", "KDBX_PASSWORD": "pw"},
    ],
)
def test_from_env_rejects_incomplete_config(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Config.from_env(env)


@pytest.mark.parametrize(
    ("value", "valid"), [("30", True), ("0.5", True), ("0", False), ("-1", False)]
)
def test_reload_interval(value: str, valid: bool) -> None:
    env = {
        "KDBX_PATH": "/db.kdbx",
        "KDBX_PASSWORD": "pw",
        "AUTH_TOKEN": "t",
        "KDBX_RELOAD_INTERVAL": value,
    }
    if valid:
        assert Config.from_env(env).reload_interval == float(value)
    else:
        with pytest.raises(ConfigError):
            Config.from_env(env)


def test_secret_file_reloads_on_change(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("old\n")
    secret = SecretFile(path)
    assert secret.get() == "old"

    path.write_text("rotated\n")
    assert secret.get() == "rotated"


@pytest.mark.parametrize("change", ["empty", "deleted"])
def test_secret_file_keeps_value_on_bad_change(tmp_path: Path, change: str) -> None:
    path = tmp_path / "token"
    path.write_text("old")
    secret = SecretFile(path)

    if change == "empty":
        path.write_text("")
    else:
        path.unlink()
    assert secret.get() == "old"

    path.write_text("new-token")
    assert secret.get() == "new-token"
