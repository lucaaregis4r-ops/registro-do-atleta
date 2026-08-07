from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path

from registro_atleta.api.review import apply_identity_review


@dataclass(frozen=True)
class IdentityReviewImportResult:
    applied_reviews: int = 0
    skipped_rows: int = 0
    invalid_rows: int = 0
    blocked_reason: str | None = None


def import_identity_reviews(
    csv_path: Path,
    database_path: Path,
    reviewed_by: str,
    confirm: bool,
) -> IdentityReviewImportResult:
    if not confirm:
        return IdentityReviewImportResult(blocked_reason="Importacao bloqueada: use --confirm para aplicar decisoes humanas.")
    if not csv_path.exists():
        return IdentityReviewImportResult(blocked_reason=f"Arquivo nao encontrado: {csv_path}")

    applied = 0
    skipped = 0
    invalid = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            decision = (row.get("decision") or "").strip()
            if not decision:
                skipped += 1
                continue
            if decision not in {"confirm_match", "reject_match", "create_new_athlete"}:
                invalid += 1
                continue
            candidate_id = (row.get("candidate_id") or "").strip()
            selected = (row.get("selected_athlete_id") or "").strip() or None
            new_athlete_name = (row.get("new_athlete_name") or "").strip() or None
            notes = (row.get("notes") or "").strip() or None
            try:
                apply_identity_review(
                    database_path=database_path,
                    candidate_id=candidate_id,
                    decision=decision,
                    reviewed_by=reviewed_by,
                    selected_athlete_id=selected,
                    new_athlete_name=new_athlete_name,
                    notes=notes,
                )
            except ValueError:
                invalid += 1
                continue
            applied += 1
    return IdentityReviewImportResult(applied_reviews=applied, skipped_rows=skipped, invalid_rows=invalid)
