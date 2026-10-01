"""OS file locks: held by a launch while it runs (launch.LaunchLock), and
around every change to the saved setups (setups.SetupStore), so two
processes (the launcher window and a launch, say) can't lose each other's
writes. The OS lets go of a lock when its process ends.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO


def lock(handle: IO[bytes]) -> None:
    """Take the lock now, or raise OSError."""
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# One threading lock per file, for threads of this process (an OS file lock
# on Windows isn't shared between handles of one process the same way).
_in_process: dict[str, threading.Lock] = {}
_registry = threading.Lock()


@contextlib.contextmanager
def held(path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    """Hold `path`'s lock (this process's threads and other processes alike),
    waiting up to `timeout` seconds for it. TimeoutError if it can't be had."""
    with _registry:
        inner = _in_process.setdefault(str(path), threading.Lock())
    if not inner.acquire(timeout=timeout):
        raise TimeoutError(f"{path} stayed locked")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        with path.open("a+b") as handle:
            while True:
                try:
                    lock(handle)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"{path} stayed locked") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    unlock(handle)
    finally:
        inner.release()
