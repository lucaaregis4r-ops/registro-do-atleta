from pathlib import Path

from registro_atleta.api.security import configured_api_token, token_is_allowed
from registro_atleta.api.review import (
    apply_alert_review,
    apply_duplicate_review,
    apply_identity_review,
    apply_literature_review,
    list_athletes,
    list_alert_episodes,
    list_duplicate_findings,
    list_identity_candidates,
    list_latest_briefing_items,
    list_literature_reviews,
    list_open_alerts,
    status_summary,
)
from registro_atleta.dashboard.export import build_dashboard_payload
from registro_atleta.dashboard.macrocycle import build_macrocycle_payload
from registro_atleta.quality.blockers import apply_date_review, list_date_review_items
from registro_atleta.quality.review_progress import build_review_progress_payload


def create_app(database_path: Path, api_token: str | None = None):
    try:
        from fastapi import FastAPI, Header, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("Instale as dependencias opcionais com `pip install .[api]`.") from exc

    app = FastAPI(title="Registro do Atleta Local API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    expected_token = api_token if api_token is not None else configured_api_token()

    class IdentityReviewPayload(BaseModel):
        candidate_id: str
        decision: str
        reviewed_by: str
        selected_athlete_id: str | None = None
        new_athlete_name: str | None = None
        notes: str | None = None

    class AlertReviewPayload(BaseModel):
        alert_id: str
        review_status: str
        reviewed_by: str
        notes: str | None = None

    class LiteratureReviewPayload(BaseModel):
        paper_topic_id: str
        decision: str
        reviewed_by: str
        notes: str | None = None

    class DateReviewPayload(BaseModel):
        finding_id: str
        decision: str
        reviewed_by: str
        corrected_date: str | None = None
        notes: str | None = None

    class DuplicateReviewPayload(BaseModel):
        finding_id: str
        decision: str
        reviewed_by: str
        notes: str | None = None

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    def status() -> dict[str, int]:
        return status_summary(database_path)

    @app.get("/identity/pending")
    def identity_pending(limit: int = 50, offset: int = 0, query: str | None = None) -> list[dict]:
        return list_identity_candidates(database_path, limit=limit, offset=offset, query=query)

    @app.get("/athletes")
    def athletes(limit: int = 100, offset: int = 0, query: str | None = None) -> list[dict]:
        return list_athletes(database_path, limit=limit, offset=offset, query=query)

    @app.post("/identity/reviews")
    def identity_reviews(payload: IdentityReviewPayload, x_registro_atleta_token: str | None = Header(default=None)) -> dict:
        _require_write_token(expected_token, x_registro_atleta_token, HTTPException)
        try:
            return apply_identity_review(database_path, **payload.model_dump()).__dict__
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/alerts/open")
    def alerts_open(limit: int = 50, offset: int = 0, severity: str | None = None, alert_type: str | None = None) -> list[dict]:
        return list_open_alerts(database_path, limit=limit, offset=offset, severity=severity, alert_type=alert_type)

    @app.get("/alert-episodes")
    def alert_episodes(
        limit: int = 50,
        offset: int = 0,
        novelty_status: str | None = None,
        episode_status: str | None = None,
    ) -> list[dict]:
        return list_alert_episodes(
            database_path,
            limit=limit,
            offset=offset,
            novelty_status=novelty_status,
            episode_status=episode_status,
        )

    @app.get("/briefing/latest/items")
    def briefing_latest_items(limit: int = 50, main_only: bool = False) -> list[dict]:
        return list_latest_briefing_items(database_path, limit=limit, main_only=main_only)

    @app.get("/quality/dates")
    def quality_dates(limit: int = 50, offset: int = 0) -> list[dict]:
        return list_date_review_items(database_path, limit=limit, offset=offset)

    @app.post("/quality/date-reviews")
    def quality_date_reviews(payload: DateReviewPayload, x_registro_atleta_token: str | None = Header(default=None)) -> dict:
        _require_write_token(expected_token, x_registro_atleta_token, HTTPException)
        try:
            return apply_date_review(database_path, **payload.model_dump()).__dict__
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/quality/duplicates")
    def quality_duplicates(limit: int = 50, offset: int = 0, status: str = "open") -> list[dict]:
        return list_duplicate_findings(database_path, limit=limit, offset=offset, status=status)

    @app.get("/quality/review-progress")
    def quality_review_progress() -> dict:
        return build_review_progress_payload(database_path)

    @app.post("/quality/duplicate-reviews")
    def quality_duplicate_reviews(payload: DuplicateReviewPayload, x_registro_atleta_token: str | None = Header(default=None)) -> dict:
        _require_write_token(expected_token, x_registro_atleta_token, HTTPException)
        try:
            return apply_duplicate_review(database_path, **payload.model_dump()).__dict__
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/alerts/reviews")
    def alerts_reviews(payload: AlertReviewPayload, x_registro_atleta_token: str | None = Header(default=None)) -> dict:
        _require_write_token(expected_token, x_registro_atleta_token, HTTPException)
        try:
            return apply_alert_review(database_path, **payload.model_dump()).__dict__
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/literature/pending")
    def literature_pending(limit: int = 50, offset: int = 0, topic: str | None = None, status: str | None = None) -> list[dict]:
        return list_literature_reviews(database_path, limit=limit, offset=offset, topic=topic, status=status)

    @app.post("/literature/reviews")
    def literature_reviews(payload: LiteratureReviewPayload, x_registro_atleta_token: str | None = Header(default=None)) -> dict:
        _require_write_token(expected_token, x_registro_atleta_token, HTTPException)
        try:
            return apply_literature_review(database_path, **payload.model_dump()).__dict__
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/dashboard/summary")
    def dashboard_summary() -> dict:
        return build_dashboard_payload(database_path)

    @app.get("/macrocycle")
    def macrocycle(weeks: int = 6) -> dict:
        return build_macrocycle_payload(database_path, weeks=weeks)

    dashboard_dir = Path(__file__).resolve().parents[3] / "apps" / "dashboard"
    if dashboard_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

    return app


def _require_write_token(expected_token: str | None, provided_token: str | None, http_exception_type) -> None:
    if not token_is_allowed(expected_token, provided_token):
        raise http_exception_type(status_code=403, detail="token local invalido")
