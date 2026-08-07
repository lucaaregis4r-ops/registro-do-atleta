from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
import urllib.request

from registro_atleta.audit.hashing import file_sha256, group_duplicates
from registro_atleta.audit.xlsx_inspector import WorkbookSummary, compact_headers, inspect_workbook


@dataclass(frozen=True)
class HistoricalFileInventory:
    path: Path
    size_bytes: int
    sha256: str
    domain: str
    workbook: WorkbookSummary


@dataclass(frozen=True)
class OnlineSourceCheck:
    source_id: str
    url: str
    status: str
    detail: str


def inventory_historical_files(root: Path) -> list[HistoricalFileInventory]:
    files = sorted(root.glob("*.xlsx"))
    inventories: list[HistoricalFileInventory] = []
    for path in files:
        inventories.append(
            HistoricalFileInventory(
                path=path,
                size_bytes=path.stat().st_size,
                sha256=file_sha256(path),
                domain=classify_domain(path.name),
                workbook=inspect_workbook(path),
            )
        )
    return inventories


def classify_domain(filename: str) -> str:
    normalized = filename.lower()
    if "prototipo" in normalized or "analise" in normalized or "relatorio" in normalized:
        return "derived_reference"
    if "chamada" in normalized or "psr" in normalized:
        return "psr"
    if "reabilita" in normalized:
        return "physio_rehab"
    if "report semanal" in normalized:
        return "weekly_physio_report"
    if "caracteriza" in normalized:
        return "assessment_or_roster"
    if "registro_unificador" in normalized:
        return "identity_seed_derived"
    return "unknown"


def check_google_sheet_csv(source_id: str, spreadsheet_id: str, gid: str, timeout: int = 12) -> OnlineSourceCheck:
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
    request = urllib.request.Request(csv_url, headers={"User-Agent": "RegistroAtleta-Audit/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            sample = response.read(1024)
            status_code = getattr(response, "status", "unknown")
            content_type = response.headers.get("content-type", "unknown")
            if sample:
                detail = f"HTTP {status_code}; content-type={content_type}; leitura inicial permitida"
                status = "accessible"
            else:
                detail = f"HTTP {status_code}; content-type={content_type}; sem conteudo inicial"
                status = "empty_or_blocked"
    except urllib.error.HTTPError as exc:
        status = "blocked_or_requires_auth"
        detail = f"HTTP {exc.code}; {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - inventory must report failures, not crash.
        status = "not_verified"
        detail = f"{type(exc).__name__}: {exc}"
    return OnlineSourceCheck(source_id=source_id, url=csv_url, status=status, detail=detail)


def render_markdown(
    inventories: list[HistoricalFileInventory],
    online_checks: list[OnlineSourceCheck],
    source_root: Path,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hashes = {item.path: item.sha256 for item in inventories}
    duplicates = group_duplicates(hashes)

    lines = [
        "# Inventario De Fontes",
        "",
        f"Gerado em UTC: `{generated_at}`",
        "",
        "## Resumo",
        "",
        f"- Raiz historica analisada: `{source_root}`",
        f"- Arquivos XLSX encontrados: {len(inventories)}",
        f"- Grupos de duplicatas por SHA-256: {len(duplicates)}",
        "",
        "## Arquivos Historicos",
        "",
        "| Arquivo | Dominio inferido | Tamanho | SHA-256 | Abas |",
        "|---|---:|---:|---|---:|",
    ]

    for item in inventories:
        lines.append(
            "| "
            f"`{item.path.name}` | {item.domain} | {item.size_bytes} | `{item.sha256}` | {len(item.workbook.sheets)} |"
        )

    lines.extend(["", "## Duplicatas Por Hash", ""])
    if duplicates:
        for digest, paths in sorted(duplicates.items()):
            names = ", ".join(f"`{path.name}`" for path in paths)
            lines.append(f"- `{digest}`: {names}")
    else:
        lines.append("- Nenhuma duplicata exata encontrada.")

    lines.extend(["", "## Abas E Cabecalhos Provaveis", ""])
    for item in inventories:
        lines.extend([f"### `{item.path.name}`", "", f"Dominio inferido: `{item.domain}`", ""])
        lines.append("| Aba | Dimensao | Linhas | Colunas | Linha de cabecalho provavel | Cabecalhos provaveis |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for sheet in item.workbook.sheets:
            lines.append(
                "| "
                f"{sheet.name} | {sheet.dimension or '-'} | {sheet.max_row or '-'} | "
                f"{sheet.max_column or '-'} | {sheet.probable_header_row or '-'} | "
                f"{compact_headers(sheet.probable_headers) or '-'} |"
            )
        lines.append("")

    lines.extend(["## Fontes Online", ""])
    if online_checks:
        lines.append("| Fonte | Status | Detalhe | URL de verificacao |")
        lines.append("|---|---|---|---|")
        for check in online_checks:
            lines.append(f"| {check.source_id} | {check.status} | {check.detail} | {check.url} |")
    else:
        lines.append("- Verificacao online nao executada.")

    lines.extend(
        [
            "",
            "## O Que Ainda Nao Foi Identificado",
            "",
            "- Titulo exato da Fonte operacional A.",
            "- Metodo definitivo de autenticacao das planilhas.",
            "- Responsavel operacional por cada fonte.",
            "- Semantica final de cores, blocos e campos especificos da fisioterapia.",
            "- Quais produtos derivados devem virar testes de regressao em cada fase futura.",
        ]
    )
    return "\n".join(lines) + "\n"
