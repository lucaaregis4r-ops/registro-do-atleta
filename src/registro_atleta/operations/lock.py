from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class PipelineLock:
    path: Path
    acquired: bool = False

    def __enter__(self) -> PipelineLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Ja existe uma execucao em andamento: {self.path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(str(os.getpid()))
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.acquired and self.path.exists():
            self.path.unlink()
        self.acquired = False
