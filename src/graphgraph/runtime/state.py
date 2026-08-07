from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

STATE_VERSION = 2


def _try_advisory_lock(descriptor: int) -> None:
    """Acquire one non-blocking, process-scoped exclusive file lock."""
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_advisory_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout: float = 10.0,
    stale_seconds: float = 120.0,
) -> Iterator[None]:
    """Serialize access with an OS lock that cannot expire while held.

    ``stale_seconds`` remains in the public signature for compatibility with
    callers of the former lock-file lease. Advisory locks are released by the
    operating system when a process exits, so age-based stealing is neither
    necessary nor safe.

    The rendezvous file intentionally remains in place. Removing it around an
    unlock creates an inode race on POSIX: a waiter can lock the old inode while
    a third process creates and locks a new file at the same path.
    """
    del stale_seconds
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        except PermissionError as exc:
            if time.monotonic() - started >= timeout:
                raise exc
            time.sleep(0.025)

    acquired = False
    try:
        while not acquired:
            try:
                _try_advisory_lock(descriptor)
                acquired = True
            except OSError as exc:
                if time.monotonic() - started >= timeout:
                    raise TimeoutError(f"timed out waiting for state lock: {lock_path}") from exc
                time.sleep(0.025)

        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()} {time.time()}\n".encode("ascii"))
        yield
    finally:
        if descriptor is not None:
            try:
                if acquired:
                    _release_advisory_lock(descriptor)
            finally:
                os.close(descriptor)


def replace_with_retry(temp_path: Path, path: Path, *, timeout: float = 2.0) -> None:
    """Commit a staged temp file over *path*, tolerating Windows sharing.

    ``file_lock`` serializes writers against other writers, but readers take
    no lock -- they just ``read_text``. On Windows ``os.replace`` fails with
    PermissionError while any handle is open on the destination, so a reader
    landing in that window would otherwise lose the write outright and strand
    the temp file next to the target.

    Public because every durable writer in the project needs this rule, not
    just this module: the graph store learned the same lesson independently
    after a transient reader could destroy a completed scan.
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
    replace_with_retry(temp_path, path)


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
