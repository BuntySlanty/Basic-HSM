"""OS-released lock: no stale lock problem after a crash."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.file = open(Path(directory)/"application.lock", "a+b")
        try:
            if self.file.seek(0, os.SEEK_END) == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Reception is already running for this data folder.") from None

    def close(self):
        self.file.close()
