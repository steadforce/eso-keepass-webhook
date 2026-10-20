"""Configuration from environment variables."""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# (inode, mtime, size) of a file; None for a file that cannot be read.
type FileSignature = tuple[int, int, int] | None


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    database: Path
    password: str | None
    password_file: Path | None
    keyfile: Path | None
    auth_token: str
    auth_token_file: Path | None
    port: int
    log_level: str
    reload_interval: float

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        database = env.get("KDBX_PATH")
        if not database:
            raise ConfigError("KDBX_PATH is required")

        password = env.get("KDBX_PASSWORD") or None
        password_file = _path(env.get("KDBX_PASSWORD_FILE"))
        keyfile = _path(env.get("KDBX_KEYFILE"))
        if not (password or password_file or keyfile):
            raise ConfigError(
                "one of KDBX_PASSWORD_FILE, KDBX_PASSWORD or KDBX_KEYFILE is required"
            )

        token_file = _path(env.get("AUTH_TOKEN_FILE"))
        auth_token = read_secret(token_file) if token_file else env.get("AUTH_TOKEN", "")
        if not auth_token:
            raise ConfigError("AUTH_TOKEN_FILE or AUTH_TOKEN is required")

        return cls(
            database=Path(database),
            password=password,
            password_file=password_file,
            keyfile=keyfile,
            auth_token=auth_token,
            auth_token_file=token_file,
            port=int(env.get("PORT", "8080")),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            reload_interval=_positive(env, "KDBX_RELOAD_INTERVAL", "10"),
        )


def read_secret(path: Path) -> str:
    """Read a secret from a file, ignoring a trailing newline."""
    return path.read_text().rstrip("\r\n")


def file_signature(path: Path) -> FileSignature:
    # stat() follows symlinks, so Kubernetes' atomic Secret updates change the inode.
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_ino, st.st_mtime_ns, st.st_size


class SecretFile:
    """A secret read from a file and re-read whenever the file changes.

    A change that leaves the file unreadable or empty keeps the previous value.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._signature = file_signature(path)
        self._value = read_secret(path)

    def get(self) -> str:
        signature = file_signature(self._path)
        if signature == self._signature:
            return self._value
        self._signature = signature
        try:
            value = read_secret(self._path)
        except OSError as e:
            log.error("cannot read %s (%s); keeping the previous value", self._path, e)
            return self._value
        if not value:
            log.error("%s is empty; keeping the previous value", self._path)
            return self._value
        self._value = value
        log.info("reloaded %s", self._path)
        return value


def _positive(env: Mapping[str, str], name: str, default: str) -> float:
    value = float(env.get(name, default))
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None
