"""Single local publisher. A durable undo directory survives process interruption."""

import errno
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    _move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    _move.restype = wintypes.BOOL
else:
    import fcntl

FILES = ("output.csv", "ufc_fighters.db", "collection-success.json",
         "event-refresh-state.json", "fighter-source-times.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def baseline(root):
    return {name: digest(root / name) for name in FILES}


def sync(path):
    if os.name == "nt":
        # Windows cannot fsync a directory. durable_replace uses write-through
        # moves for every journal and publication rename instead.
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_replace(src, dest):
    if os.name == "nt":
        # Same-volume only: deliberately omit MOVEFILE_COPY_ALLOWED.
        # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
        if not _move(str(Path(src).resolve()), str(Path(dest).resolve()), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(src, dest)


def write_json(path, data):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as f:
        json.dump(data, f, indent=2, default=str, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    durable_replace(f.name, path)
    sync(path.parent)


@contextmanager
def locked(root):
    with (root / ".refresh.lock").open("a+b") as file:
        if os.name == "nt":
            # msvcrt locks a byte range from the current offset, even past EOF.
            file.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise ValueError("Another refresh holds the local lock") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)


def install(src, dest):
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as f:
        if os.name != "nt":
            os.fchmod(f.fileno(), (dest if dest.exists() else src).stat().st_mode & 0o777)
        with src.open("rb") as stream:
            shutil.copyfileobj(stream, f)
        f.flush()
        os.fsync(f.fileno())
    durable_replace(f.name, dest)


def retire(root, journal):
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        durable_replace(journal, Path(tmp) / "retired")
        sync(root)


def recover(root):
    journal = root / ".refresh-undo"
    if journal.exists():
        for name in FILES:
            if (journal / name).exists():
                install(journal / name, root / name)
            else:
                (root / name).unlink(missing_ok=True)
        sync(root)
        retire(root, journal)


def replace(root, stage, report, changed):
    for suffix in ("-wal", "-shm", "-journal"):
        if (root / ("ufc_fighters.db" + suffix)).exists():
            raise ValueError(
                "SQLite has an active sidecar; close writers and checkpoint before replacement"
            )
    journal = root / ".refresh-undo"
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        undo = Path(tmp) / "undo"
        undo.mkdir()
        for name in FILES:
            if (root / name).exists():
                install(root / name, undo / name)
        sync(undo)
        durable_replace(undo, journal)
        sync(root)
    try:
        if changed:
            for name in FILES[:2]:
                install(stage / name, root / name)
        for name in FILES[3:]:
            if (stage / name).exists():
                install(stage / name, root / name)
        write_json(root / FILES[2], report)
        retire(root, journal)
    except Exception:
        recover(root)
        raise
