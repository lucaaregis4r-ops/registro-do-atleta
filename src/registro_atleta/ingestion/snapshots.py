from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import urllib.request

from registro_atleta.ingestion.sources import SourceConfig


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect_snapshot(source: SourceConfig, run_id: str, root: Path) -> Path:
    collected_at = datetime.now(timezone.utc)
    date_part = collected_at.strftime("%Y-%m-%d")
    target_dir = root / "data" / "raw" / source.source_type / source.source_id / date_part
    target_dir.mkdir(parents=True, exist_ok=True)

    if source.source_type == "google_sheet":
        if not source.spreadsheet_id or source.gid is None:
            raise ValueError(f"Fonte Google sem spreadsheet_id/gid: {source.source_id}")
        target = target_dir / f"{run_id}.csv"
        csv_url = (
            f"https://docs.google.com/spreadsheets/d/{source.spreadsheet_id}/gviz/tq?"
            f"tqx=out:csv&gid={source.gid}"
        )
        request = urllib.request.Request(csv_url, headers={"User-Agent": "RegistroAtleta-Sync/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            target.write_bytes(response.read())
        return target

    if source.source_type == "local_xlsx":
        if source.local_path is None:
            raise ValueError(f"Fonte local sem caminho: {source.source_id}")
        target = target_dir / source.local_path.name
        shutil.copy2(source.local_path, target)
        return target

    raise ValueError(f"Tipo de fonte nao suportado: {source.source_type}")
