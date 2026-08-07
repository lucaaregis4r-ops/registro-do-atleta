from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    source_type: str
    name: str
    domain: str
    enabled: bool
    url: str | None = None
    spreadsheet_id: str | None = None
    gid: str | None = None
    local_path: Path | None = None


def default_sources(root: Path) -> list[SourceConfig]:
    historical_root = root / "data" / "input"
    sources: list[SourceConfig] = []

    for path in sorted(historical_root.glob("*.xlsx")):
        sources.append(
            SourceConfig(
                source_id=f"historical_{_slug(path.stem)}",
                source_type="local_xlsx",
                name=path.name,
                domain="historical_pending_domain_normalization",
                enabled=True,
                local_path=path,
            )
        )
    return sources


def _slug(value: str) -> str:
    keep = []
    for char in value.lower():
        if char.isalnum():
            keep.append(char)
        else:
            keep.append("_")
    slug = "".join(keep).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug
