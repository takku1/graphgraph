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
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()} {time.time()}\n".encode("ascii"))
        except FileExistsError:
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
    temp_path.replace(path)


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
