from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def group_duplicates(hashes: dict[Path, str]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path, digest in hashes.items():
        grouped[digest].append(path)
    return {digest: paths for digest, paths in grouped.items() if len(paths) > 1}
