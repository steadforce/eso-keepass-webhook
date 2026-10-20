from pathlib import Path

import pytest
from pykeepass import create_database

PASSWORD = "test-password"
CERT = b"\x30\x82\x01\x0a\xff binary certificate"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    """A database with nested groups, custom fields, attachments, references and duplicates."""
    path = tmp_path / "test.kdbx"
    kp = create_database(str(path), password=PASSWORD)
    kp.add_entry(kp.root_group, "top", "top-user", "top-pass")

    apps = kp.add_group(kp.root_group, "apps")
    postgres = kp.add_group(apps, "postgres")
    entry = kp.add_entry(postgres, "admin", "pgadmin", "pg-pass", url="postgres://db")
    entry.set_custom_property("API KEY", "abc 123", protect=True)
    entry.add_attachment(kp.add_binary(CERT), "tls.crt")

    # Like KeePassXC's "Clone entry" with "Replace username and password with references"
    admin = entry.uuid.hex.upper()
    clone = kp.add_entry(postgres, "clone", f"{{REF:U@I:{admin}}}", f"{{REF:P@I:{admin}}}")
    clone.notes = "literal {REF:not a reference}"
    clone_ref = f"{{REF:P@I:{clone.uuid.hex.upper()}}}"
    kp.add_entry(postgres, "chained", "c", clone_ref)
    kp.add_entry(postgres, "broken", "b", "{REF:P@I:00000000000000000000000000000000}")

    clash = kp.add_entry(apps, "clash", "x", "y")
    clash.set_custom_property("config", "field")
    clash.add_attachment(kp.add_binary(b"attachment"), "config")

    kp.add_entry(apps, "twice", "a", "1")
    kp.add_entry(apps, "twice", "b", "2", force_creation=True)
    kp.add_group(kp.root_group, "same")
    kp.add_group(kp.root_group, "same")
    kp.save()
    return path
