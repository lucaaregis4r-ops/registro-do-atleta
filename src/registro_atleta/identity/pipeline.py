from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.identity.extraction import ExtractedIdentity, extract_identities
from registro_atleta.identity.normalization import normalize_name
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class IdentityBuildResult:
    athletes_created: int = 0
    aliases_created: int = 0
    candidates_created: int = 0
    auto_matched: int = 0
    pending_review: int = 0
    memberships_created: int = 0
    report_path: Path | None = None
    review_queue_path: Path | None = None


def build_identity(root: Path, database_path: Path | None = None) -> IdentityBuildResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    result = IdentityBuildResult()
    now = utc_now()

    with connection:
        seed_identities = _seed_identities(connection)
        for identity in seed_identities:
            athlete_id, created = _ensure_athlete(connection, identity.name_raw, identity.name_normalized, now)
            if created:
                result.athletes_created += 1
            if _ensure_alias(connection, athlete_id, identity.name_raw, identity.source_id, confirmed=True, now=now):
                result.aliases_created += 1
            if _ensure_membership(connection, athlete_id, identity):
                result.memberships_created += 1

        known_aliases = _known_aliases(connection)
        extracted_identities = extract_identities(connection)
        seen_source_record_ids = {identity.source_record_id for identity in extracted_identities}
        for identity in extracted_identities:
            athlete_id = known_aliases.get(identity.name_normalized)
            status = "auto_matched" if athlete_id else "pending_review"
            confidence = 1.0 if athlete_id else 0.0
            if _ensure_candidate(connection, identity, athlete_id, confidence, status, now):
                result.candidates_created += 1

        _mark_stale_candidates(connection, seen_source_record_ids)
        result.auto_matched = _count_candidates(connection, "auto_matched")
        result.pending_review = _count_candidates(connection, "pending_review")

    result.review_queue_path = _write_review_queue(root, connection)
    result.report_path = _write_identity_report(root, result)
    connection.close()
    return result


def _seed_identities(connection: sqlite3.Connection) -> list[ExtractedIdentity]:
    rows = connection.execute(
        """
        SELECT source_record_id, source_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1
          AND source_id LIKE 'historical_registro_atletas_demo%'
        ORDER BY source_id, source_row_key
        """
    ).fetchall()
    identities: list[ExtractedIdentity] = []
    for row in rows:
        payload = json.loads(row["raw_payload_json"])
        if payload.get("sheet") != "Registro_Unificado":
            continue
        values = payload.get("values", [])
        if not isinstance(values, list) or len(values) < 3:
            continue
        name = str(values[1]).strip()
        if name == "Nome_canônico":
            continue
        identities.append(
            ExtractedIdentity(
                source_record_id=row["source_record_id"],
                source_id=row["source_id"],
                name_raw=name,
                name_normalized=normalize_name(name),
                sport=str(values[3]).strip() if len(values) > 3 and str(values[3]).strip() else None,
                category=str(values[4]).strip() if len(values) > 4 and str(values[4]).strip() else None,
                evidence={"method": "identity_seed", "sheet": "Registro_Unificado"},
            )
        )
    return identities


def _ensure_athlete(
    connection: sqlite3.Connection,
    canonical_name: str,
    normalized_name: str,
    now: str,
) -> tuple[str, bool]:
    existing = connection.execute(
        "SELECT athlete_id FROM athletes WHERE normalized_name = ?",
        (normalized_name,),
    ).fetchone()
    if existing:
        return existing["athlete_id"], False

    next_number = connection.execute("SELECT COUNT(*) + 1 FROM athletes").fetchone()[0]
    athlete_id = f"OLY-ATH-{next_number:06d}"
    connection.execute(
        """
        INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (athlete_id, canonical_name, normalized_name, now, now),
    )
    return athlete_id, True


def _ensure_alias(
    connection: sqlite3.Connection,
    athlete_id: str,
    alias_raw: str,
    source_id: str | None,
    confirmed: bool,
    now: str,
) -> bool:
    alias_normalized = normalize_name(alias_raw)
    existing = connection.execute(
        """
        SELECT alias_id FROM athlete_aliases
        WHERE athlete_id = ? AND alias_normalized = ? AND COALESCE(source_id, '') = COALESCE(?, '')
        """,
        (athlete_id, alias_normalized, source_id),
    ).fetchone()
    if existing:
        return False
    connection.execute(
        """
        INSERT INTO athlete_aliases
        (alias_id, athlete_id, alias_raw, alias_normalized, source_id, is_confirmed, confirmed_by, confirmed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            athlete_id,
            alias_raw,
            alias_normalized,
            source_id,
            1 if confirmed else 0,
            "seed_import" if confirmed else None,
            now if confirmed else None,
        ),
    )
    return True


def _ensure_membership(connection: sqlite3.Connection, athlete_id: str, identity: ExtractedIdentity) -> bool:
    if not identity.sport and not identity.category:
        return False
    existing = connection.execute(
        """
        SELECT membership_id FROM athlete_memberships
        WHERE athlete_id = ? AND COALESCE(sport, '') = COALESCE(?, '')
          AND COALESCE(category, '') = COALESCE(?, '')
          AND COALESCE(source_record_id, '') = COALESCE(?, '')
        """,
        (athlete_id, identity.sport, identity.category, identity.source_record_id),
    ).fetchone()
    if existing:
        return False
    connection.execute(
        """
        INSERT INTO athlete_memberships
        (membership_id, athlete_id, sport, category, source_record_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (uuid4().hex, athlete_id, identity.sport, identity.category, identity.source_record_id),
    )
    return True


def _known_aliases(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT alias_normalized, athlete_id
        FROM athlete_aliases
        WHERE is_confirmed = 1
        """
    ).fetchall()
    return {row["alias_normalized"]: row["athlete_id"] for row in rows}


def _count_candidates(connection: sqlite3.Connection, status: str) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = ?",
        (status,),
    ).fetchone()[0]


def _mark_stale_candidates(connection: sqlite3.Connection, seen_source_record_ids: set[str]) -> None:
    rows = connection.execute(
        """
        SELECT candidate_id, source_record_id
        FROM identity_candidates
        WHERE decision_status IN ('auto_matched', 'pending_review')
        """
    ).fetchall()
    stale_ids = [row["candidate_id"] for row in rows if row["source_record_id"] not in seen_source_record_ids]
    if not stale_ids:
        return
    connection.executemany(
        "UPDATE identity_candidates SET decision_status = 'stale' WHERE candidate_id = ?",
        [(candidate_id,) for candidate_id in stale_ids],
    )


def _ensure_candidate(
    connection: sqlite3.Connection,
    identity: ExtractedIdentity,
    proposed_athlete_id: str | None,
    confidence: float,
    status: str,
    now: str,
) -> bool:
    existing = connection.execute(
        "SELECT candidate_id FROM identity_candidates WHERE source_record_id = ?",
        (identity.source_record_id,),
    ).fetchone()
    evidence = dict(identity.evidence)
    evidence["source_id"] = identity.source_id
    if existing:
        connection.execute(
            """
            UPDATE identity_candidates
            SET name_raw = ?, name_normalized = ?, sport = ?, category = ?,
                proposed_athlete_id = ?, confidence = ?, evidence_json = ?, decision_status = ?
            WHERE candidate_id = ?
            """,
            (
                identity.name_raw,
                identity.name_normalized,
                identity.sport,
                identity.category,
                proposed_athlete_id,
                confidence,
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                status,
                existing["candidate_id"],
            ),
        )
        return False
    connection.execute(
        """
        INSERT INTO identity_candidates
        (candidate_id, source_record_id, name_raw, name_normalized, sport, category,
         proposed_athlete_id, confidence, evidence_json, decision_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            identity.source_record_id,
            identity.name_raw,
            identity.name_normalized,
            identity.sport,
            identity.category,
            proposed_athlete_id,
            confidence,
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            status,
            now,
        ),
    )
    return True


def _write_identity_report(root: Path, result: IdentityBuildResult) -> Path:
    report_dir = root / "data" / "reports" / "identity"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"identity-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    lines = [
        "# Relatorio De Identidade",
        "",
        f"- atletas_criados: `{result.athletes_created}`",
        f"- aliases_criados: `{result.aliases_created}`",
        f"- memberships_criados: `{result.memberships_created}`",
        f"- candidatos_criados: `{result.candidates_created}`",
        f"- associados_automaticamente: `{result.auto_matched}`",
        f"- pendentes_revisao: `{result.pending_review}`",
        f"- fila_revisao: `{result.review_queue_path}`",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _write_review_queue(root: Path, connection: sqlite3.Connection) -> Path:
    review_dir = root / "data" / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / "identity_pending.csv"
    rows = connection.execute(
        """
        SELECT candidate_id, source_record_id, name_raw, name_normalized, sport, category, confidence, evidence_json
        FROM identity_candidates
        WHERE decision_status = 'pending_review'
        ORDER BY name_normalized, source_record_id
        """
    ).fetchall()
    with review_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "candidate_id",
                "source_record_id",
                "name_raw",
                "name_normalized",
                "sport",
                "category",
                "confidence",
                "decision",
                "selected_athlete_id",
                "notes",
                "evidence_json",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["candidate_id"],
                    row["source_record_id"],
                    row["name_raw"],
                    row["name_normalized"],
                    row["sport"] or "",
                    row["category"] or "",
                    row["confidence"],
                    "",
                    "",
                    "",
                    row["evidence_json"],
                ]
            )
    return review_path
