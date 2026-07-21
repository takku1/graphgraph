from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

STATE_VERSION = 2


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout: float = 10.0,
    stale_seconds: float = 120.0,
) -> Iterator[None]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    descriptor: int | None = None
    denied: PermissionError | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()} {time.time()}\n".encode("ascii"))
        except (FileExistsError, PermissionError) as exc:
            # Windows reports contention two different ways. A held lock gives
            # FileExistsError, but a lock the previous holder has just
            # unlinked lingers in "delete pending" until the last handle
            # closes, and opening it in that window raises PermissionError
            # (ERROR_ACCESS_DENIED) instead. Treating only the former as
            # contention let the latter escape and kill the waiting thread
            # under concurrent load.
            denied = exc if isinstance(exc, PermissionError) else None
            try:
                stale = time.time() - lock_path.stat().st_mtime > stale_seconds
            except OSError:
                stale = False
            if stale:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() - started >= timeout:
                # A genuine permission problem (read-only directory) also
                # lands here, so surface the real error rather than a
                # misleading timeout that hides the cause.
                if denied is not None:
                    raise denied
                raise TimeoutError(f"timed out waiting for state lock: {lock_path}")
            time.sleep(0.025)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink()
        except OSError:
            pass


def _replace_with_retry(temp_path: Path, path: Path, *, timeout: float = 2.0) -> None:
    """Commit a staged temp file over *path*, tolerating Windows sharing.

    ``file_lock`` serializes writers against other writers, but readers take
    no lock -- they just ``read_text``. On Windows ``os.replace`` fails with
    PermissionError while any handle is open on the destination, so a reader
    landing in that window would otherwise lose the write outright and strand
    the temp file next to the target.
    """
    started = time.monotonic()
    while True:
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            if time.monotonic() - started >= timeout:
                # Genuine, non-transient failure: don't leave the staged temp
                # file behind as litter, and let the real error surface.
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise
            time.sleep(0.025)


def atomic_write_text(path: Path, text: str, *, lock: bool = True) -> None:
    if lock:
        with file_lock(path):
            atomic_write_text(path, text, lock=False)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
        newline="\n",
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    _replace_with_retry(temp_path, path)


def atomic_write_json(
    path: Path,
    data: object,
    *,
    indent: int | None = 2,
    lock: bool = True,
) -> None:
    separators = (",", ":") if indent is None else None
    text = json.dumps(data, indent=indent, ensure_ascii=False, separators=separators) + "\n"
    atomic_write_text(path, text, lock=lock)


def append_jsonl(path: Path, data: object) -> None:
    append_jsonl_many(path, (data,))


def append_jsonl_many(path: Path, rows) -> None:
    with file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for data in rows:
                handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
