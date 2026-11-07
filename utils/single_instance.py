"""
One MXB at a time. With "start with Windows" on, opening MXB again from the Start menu would
otherwise start a second copy fighting the first for the microphone and the hotkeys.

QLockFile writes our PID into the lock; if MXB crashes, the next start sees the PID is gone and
takes the lock over, so a crash can never lock you out.
"""
from PySide6.QtCore import QLockFile
from utils.paths import data_file


def acquire(name: str = "mxb.lock", wait_ms: int = 200) -> QLockFile | None:
    """Returns the held lock (keep a reference for the app's lifetime) or None if MXB is already running."""
    lock = QLockFile(str(data_file(name)))
    lock.setStaleLockTime(0)  # never "stale by age": only stale when the owning process is gone
    return lock if lock.tryLock(wait_ms) else None
