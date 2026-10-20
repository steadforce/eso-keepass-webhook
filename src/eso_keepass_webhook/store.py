"""Access to the KeePass database, reloaded in the background whenever its files change."""

import logging
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pykeepass import PyKeePass

from .config import FileSignature, file_signature, read_secret

log = logging.getLogger(__name__)

STANDARD_FIELDS = ("username", "password", "url", "notes")

# KeePass resolves references that point to further references; stop at some depth.
MAX_REFERENCE_DEPTH = 10

# Loads taking longer than this are logged as a warning: the key derivation is expensive.
SLOW_LOAD_SECONDS = 2.0

type Signature = tuple[FileSignature, ...]


class NotFoundError(Exception):
    pass


class AmbiguousError(Exception):
    pass


class BrokenReferenceError(Exception):
    pass


class Store:
    """A KeePass database that is reloaded when the database, password or key file changes.

    Opening fails if the database cannot be loaded. Changes are picked up by ``refresh``, which
    ``watch`` calls in the background: lookups never wait for a reload, and a reload that fails
    keeps the previously loaded version, so a broken or half-written file never interrupts
    serving.
    """

    def __init__(
        self,
        database: Path,
        *,
        password: str | None = None,
        password_file: Path | None = None,
        keyfile: Path | None = None,
    ) -> None:
        self._database = database
        self._password = password
        self._password_file = password_file
        self._keyfile = keyfile
        self._lock = threading.Lock()
        self._signature = self._stat()
        self._kp = self._load("loaded")

    def fields(self, path: str) -> dict[str, str]:
        """Return all fields of the entry at ``path``, e.g. ``"Group/Subgroup/Entry"``."""
        with self._lock:
            entry = self._entry(path)
            return {name: self._resolve(value) for name, value in _fields(entry).items()}

    def value(self, path: str, name: str) -> str | bytes:
        """Return a field of the entry at ``path``, or one of its attachments by file name."""
        with self._lock:
            entry = self._entry(path)
            field = _fields(entry).get(name)
            found: list[str | bytes] = [] if field is None else [field]
            found += [a.data for a in entry.attachments if a.filename == name]
            value = _one(found, f"field or attachment {name!r} of entry {path!r}")
            return self._resolve(value) if isinstance(value, str) else value

    def watch(self, interval: float) -> None:
        """Call ``refresh`` every ``interval`` seconds in a background thread."""
        threading.Thread(target=self._watch, args=(interval,), name="reload", daemon=True).start()

    def refresh(self) -> None:
        """Reload the database if one of its files changed since the last check."""
        signature = self._stat()
        if signature == self._signature:
            return
        self._signature = signature
        if None in signature:
            log.error("cannot read database files; serving the previously loaded version")
            return
        try:
            kp = self._load("reloaded")
        except Exception as e:
            log.error("cannot reload database (%s); serving the previously loaded version", e)
            return
        with self._lock:
            self._kp = kp

    def _watch(self, interval: float) -> None:
        while True:
            time.sleep(interval)
            try:
                self.refresh()
            except Exception:  # keep watching whatever happens
                log.exception("checking the database for changes failed")

    def _entry(self, path: str) -> Any:
        *group_names, title = path.strip("/").split("/")
        group = self._kp.root_group
        for name in group_names:
            group = _one([g for g in group.subgroups if g.name == name], f"group {name!r}")
        return _one([e for e in group.entries if e.title == title], f"entry {path!r}")

    def _resolve(self, value: str) -> str:
        """Replace KeePass field references like ``{REF:P@I:<uuid>}`` with their values."""
        for _ in range(MAX_REFERENCE_DEPTH):
            try:
                resolved = self._kp.deref(value)
            except (TypeError, ValueError):  # e.g. an invalid UUID
                resolved = None
            if resolved is None:
                raise BrokenReferenceError(f"broken field reference in {value!r}")
            if resolved == value:
                return value
            value = str(resolved)
        raise BrokenReferenceError(f"field references nested too deeply in {value!r}")

    def _load(self, verb: str) -> Any:
        password = read_secret(self._password_file) if self._password_file else self._password
        keyfile = str(self._keyfile) if self._keyfile else None
        start = time.perf_counter()
        kp = PyKeePass(str(self._database), password=password, keyfile=keyfile)
        seconds = time.perf_counter() - start
        if seconds > SLOW_LOAD_SECONDS:
            log.warning(
                "%s %s in %.1fs: its key derivation is slow, prefer Argon2 with default settings",
                verb,
                self._database,
                seconds,
            )
        else:
            log.info("%s %s in %.2fs", verb, self._database, seconds)
        return kp

    def _stat(self) -> Signature:
        files = (self._database, self._password_file, self._keyfile)
        return tuple(file_signature(f) for f in files if f)


def _fields(entry: Any) -> dict[str, str]:
    fields = {name: str(getattr(entry, name) or "") for name in STANDARD_FIELDS}
    fields.update({k: str(v or "") for k, v in entry.custom_properties.items()})
    return fields


def _one[T](items: Sequence[T], what: str) -> T:
    if not items:
        raise NotFoundError(f"{what} not found")
    if len(items) > 1:
        raise AmbiguousError(f"{what} is not unique")
    return items[0]
