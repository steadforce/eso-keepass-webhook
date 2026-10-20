import logging
import os
import time
from pathlib import Path

import pytest
from pykeepass import PyKeePass, create_database
from pykeepass.exceptions import CredentialsError

from eso_keepass_webhook import store as store_module
from eso_keepass_webhook.store import AmbiguousError, BrokenReferenceError, NotFoundError, Store

from .conftest import CERT, PASSWORD


def test_fields_returns_standard_and_custom_fields(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    assert store.fields("apps/postgres/admin") == {
        "username": "pgadmin",
        "password": "pg-pass",
        "url": "postgres://db",
        "notes": "",
        "API KEY": "abc 123",
    }


def test_fields_entry_in_root_group(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    assert store.fields("top")["password"] == "top-pass"
    assert store.fields("/top/")["password"] == "top-pass"


@pytest.mark.parametrize("path", ["missing", "apps/missing", "nope/admin", "admin"])
def test_fields_missing(database: Path, path: str) -> None:
    with pytest.raises(NotFoundError):
        Store(database, password=PASSWORD).fields(path)


@pytest.mark.parametrize("path", ["apps/twice", "same/anything"])
def test_fields_ambiguous(database: Path, path: str) -> None:
    with pytest.raises(AmbiguousError):
        Store(database, password=PASSWORD).fields(path)


def test_value_returns_field_or_attachment(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    assert store.value("apps/postgres/admin", "API KEY") == "abc 123"
    assert store.value("apps/postgres/admin", "tls.crt") == CERT


def test_value_missing_or_ambiguous(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    with pytest.raises(NotFoundError):
        store.value("apps/postgres/admin", "missing")
    with pytest.raises(AmbiguousError):
        store.value("apps/clash", "config")


def test_resolves_field_references(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    clone = store.fields("apps/postgres/clone")
    assert (clone["username"], clone["password"]) == ("pgadmin", "pg-pass")
    assert clone["notes"] == "literal {REF:not a reference}"
    assert store.value("apps/postgres/chained", "password") == "pg-pass"


def test_broken_reference(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    with pytest.raises(BrokenReferenceError):
        store.value("apps/postgres/broken", "password")
    with pytest.raises(BrokenReferenceError):
        store.fields("apps/postgres/broken")
    # Other fields of the entry are still served.
    assert store.value("apps/postgres/broken", "username") == "b"


def test_open_fails_with_wrong_password(database: Path) -> None:
    with pytest.raises(CredentialsError):
        Store(database, password="wrong")


def test_password_and_keyfile_from_files(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("file-password\n")
    keyfile = tmp_path / "keyfile"
    keyfile.write_bytes(os.urandom(64))
    path = tmp_path / "keyed.kdbx"
    kp = create_database(str(path), password="file-password", keyfile=str(keyfile))
    kp.add_entry(kp.root_group, "entry", "user", "pass")
    kp.save()

    store = Store(path, password_file=password_file, keyfile=keyfile)
    assert store.fields("entry")["password"] == "pass"


def test_refresh_reloads_changed_database(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    _add_entry(database, "new")

    # Lookups never reload: the change shows up once refresh has run.
    with pytest.raises(NotFoundError):
        store.fields("new")
    store.refresh()
    assert store.fields("new")["password"] == "new-pass"


def test_keeps_serving_when_reload_fails(database: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = Store(database, password=PASSWORD)
    valid = database.read_bytes()

    database.write_bytes(b"not a database")
    store.refresh()
    assert "cannot reload database" in caplog.text
    assert store.fields("top")["password"] == "top-pass"

    database.unlink()
    store.refresh()
    assert "cannot read database files" in caplog.text
    assert store.fields("top")["password"] == "top-pass"

    # A later, valid version is picked up again.
    database.write_bytes(valid)
    _add_entry(database, "after-fix")
    store.refresh()
    assert store.fields("after-fix")["password"] == "new-pass"


def test_watch_reloads_in_the_background(database: Path) -> None:
    store = Store(database, password=PASSWORD)
    store.watch(0.05)
    _add_entry(database, "new")

    deadline = time.monotonic() + 10
    while True:
        try:
            assert store.fields("new")["password"] == "new-pass"
            break
        except NotFoundError:
            assert time.monotonic() < deadline, "the change was not picked up"
            time.sleep(0.05)


def test_logs_load_time_and_warns_when_slow(
    database: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO)
    Store(database, password=PASSWORD)
    assert "loaded" in caplog.text
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    monkeypatch.setattr(store_module, "SLOW_LOAD_SECONDS", 0.0)
    Store(database, password=PASSWORD)
    assert "key derivation is slow" in caplog.text


def _add_entry(database: Path, title: str) -> None:
    kp = PyKeePass(str(database), password=PASSWORD)
    kp.add_entry(kp.root_group, title, "user", "new-pass")
    _replace(kp, database)


def _replace(kp: PyKeePass, path: Path) -> None:
    """Save atomically like a Kubernetes Secret update, so the inode changes."""
    tmp = path.with_suffix(".tmp")
    kp.save(str(tmp))
    tmp.replace(path)
