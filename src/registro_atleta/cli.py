from __future__ import annotations

import argparse
from pathlib import Path

from registro_atleta.alerts.pipeline import build_alerts
from registro_atleta.analytics.phase9 import assess_phase9_readiness, build_phase9_exploratory_report
from registro_atleta.audit.source_inventory import check_google_sheet_csv, inventory_historical_files, render_markdown
from registro_atleta.dashboard.export import export_dashboard_data
from registro_atleta.dashboard.macrocycle import build_macrocycle_report
from registro_atleta.domains.pipeline import build_domains
from registro_atleta.identity.pipeline import build_identity
from registro_atleta.identity.reviews import import_identity_reviews
from registro_atleta.ingestion.pipeline import sync
from registro_atleta.literature.catalog import catalog_literature_candidates, import_literature_reviews
from registro_atleta.literature.search import search_literature_candidates
from registro_atleta.llm.pipeline import build_llm_literature
from registro_atleta.llm.research_report import approve_research_report_articles, build_llm_research_report
from registro_atleta.operations.backup import list_backups, prune_backups, restore_database
from registro_atleta.operations.pipeline import run_operational_pipeline
from registro_atleta.operations.nightly_intelligence import PROFILES, run_nightly_intelligence
from registro_atleta.operations.readiness import build_operational_readiness_report
from registro_atleta.quality.blockers import build_data_readiness_report, import_date_reviews
from registro_atleta.quality.duplicates import build_duplicate_alerts
from registro_atleta.quality.review_progress import build_review_progress_report
from registro_atleta.reports.briefing import build_nightly_briefing
from registro_atleta.reports.enriched import build_approved_literature_report
from registro_atleta.reports.status import build_status_panel
from registro_atleta.reports.weekly import build_weekly_report
from registro_atleta.reports.weekly_intelligence import build_weekly_intelligence_report


ROOT = Path(__file__).resolve().parents[2]


# Fontes reais nao fazem parte da distribuicao publica. Configure fontes proprias
# antes de usar os comandos de ingestao ou execute `audit-sources --skip-online`.
GOOGLE_SOURCES: list[dict[str, str]] = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="registro-do-atleta")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit-sources", help="Inventaria fontes sem alterar arquivos originais.")
    audit_parser.add_argument("--source-root", default="data/input", help="Pasta com arquivos .xlsx historicos.")
    audit_parser.add_argument("--output", default="docs/source_inventory.md", help="Arquivo Markdown de saida.")
    audit_parser.add_argument(
        "--skip-online",
        action="store_true",
        help="Nao valida acesso inicial as planilhas Google.",
    )
    sync_parser = subparsers.add_parser("sync", help="Coleta fontes, salva snapshots e atualiza staging SQLite.")
    sync_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    identity_parser = subparsers.add_parser("build-identity", help="Cria cadastro de atletas e fila de identidade.")
    identity_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    domains_parser = subparsers.add_parser("build-domains", help="Normaliza PSR e fisioterapia ligados a atletas.")
    domains_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    alerts_parser = subparsers.add_parser("build-alerts", help="Gera baselines, alertas e achados de qualidade.")
    alerts_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    run_parser = subparsers.add_parser("run-pipeline", help="Executa rotina operacional completa com backup e lock.")
    run_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    nightly_parser = subparsers.add_parser("nightly-intelligence", help="Executa a rotina noturna modular manual.")
    nightly_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    nightly_parser.add_argument("--profile", choices=PROFILES, default="standard", help="Conjunto de blocos executados.")
    nightly_parser.add_argument("--days", type=int, default=7, help="Janela do relatorio integrado, entre 1 e 31 dias.")
    nightly_parser.add_argument("--reference-date", default=None, help="Fim da janela em YYYY-MM-DD.")
    nightly_parser.add_argument("--include-experimental", action="store_true", help="Inclui a Fase 9, ainda protegida por gate.")
    nightly_parser.add_argument("--dry-run", action="store_true", help="Mostra o plano sem executar etapas.")
    operation_readiness_parser = subparsers.add_parser("operation-readiness", help="Verifica banco, backup, restore, retencao e Agendador.")
    operation_readiness_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    operation_readiness_parser.add_argument("--keep-last", type=int, default=10, help="Limite oficial de backups mantidos.")
    operation_readiness_parser.add_argument("--task-name", default="Registro do Atleta Nightly", help="Nome esperado no Agendador do Windows.")
    operation_readiness_parser.add_argument("--manual", action="store_true", help="Declara rotina manual; nao exige tarefa no Agendador.")
    weekly_parser = subparsers.add_parser("weekly-report", help="Gera relatorio semanal deterministico.")
    weekly_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    weekly_intelligence_parser = subparsers.add_parser("weekly-intelligence-report", help="Integra mudancas semanais deterministicas e literatura estruturada.")
    weekly_intelligence_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    weekly_intelligence_parser.add_argument("--days", type=int, default=7, help="Janela de mudancas, entre 1 e 31 dias.")
    weekly_intelligence_parser.add_argument("--reference-date", default=None, help="Fim da janela em YYYY-MM-DD.")
    status_parser = subparsers.add_parser("status-panel", help="Gera painel HTML local de status.")
    status_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    briefing_parser = subparsers.add_parser("nightly-briefing", help="Gera briefing matinal orientado por mudancas.")
    briefing_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    briefing_parser.add_argument("--main-limit", type=int, default=12, help="Maximo de itens no briefing principal.")
    briefing_parser.add_argument("--reference-date", default=None, help="Data de referencia YYYY-MM-DD.")
    approved_lit_parser = subparsers.add_parser("approved-literature-report", help="Gera boletim com literatura aprovada.")
    approved_lit_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    backups_parser = subparsers.add_parser("backups", help="Lista ou aplica retencao de backups.")
    backups_parser.add_argument("--keep-last", type=int, default=None, help="Mantem apenas os N backups mais recentes.")
    restore_parser = subparsers.add_parser("restore-backup", help="Restaura um backup para o banco local.")
    restore_parser.add_argument("backup", help="Caminho do backup .db.")
    restore_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    restore_parser.add_argument("--confirm", action="store_true", help="Confirmacao obrigatoria para sobrescrever o banco.")
    llm_parser = subparsers.add_parser("build-llm-literature", help="Gera resumo LLM seguro e temas de literatura.")
    llm_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    llm_research_parser = subparsers.add_parser("llm-research-report", help="Gera relatorio cientifico com LLM, Crossref e artigos candidatos.")
    llm_research_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    llm_research_parser.add_argument("--max-queries", type=int, default=5, help="Numero maximo de chaves de pesquisa geradas pelo LLM.")
    llm_research_parser.add_argument("--results-per-query", type=int, default=3, help="Resultados Crossref por chave de pesquisa.")
    approve_research_parser = subparsers.add_parser("approve-research-report-articles", help="Aprova artigos candidatos listados em relatorio LLM/Crossref.")
    approve_research_parser.add_argument("--input", required=True, help="Relatorio llm-research-report-*.md.")
    approve_research_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    approve_research_parser.add_argument("--reviewed-by", required=True, help="Pessoa responsavel pela aprovacao.")
    approve_research_parser.add_argument("--notes", default=None, help="Observacao de auditoria.")
    catalog_parser = subparsers.add_parser("catalog-literature", help="Cataloga candidatos de artigos a partir de CSV local.")
    catalog_parser.add_argument("--input", required=True, help="CSV com artigos candidatos.")
    catalog_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    catalog_parser.add_argument("--confirm", action="store_true", help="Confirmacao obrigatoria para gravar artigos candidatos.")
    reviews_parser = subparsers.add_parser("import-literature-reviews", help="Aplica decisoes humanas da fila de literatura.")
    reviews_parser.add_argument("--input", default="data/reviews/literature_review_queue.csv", help="CSV de revisao de literatura.")
    reviews_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    reviews_parser.add_argument("--reviewed-by", required=True, help="Pessoa responsavel pela revisao.")
    reviews_parser.add_argument("--confirm", action="store_true", help="Confirmacao obrigatoria para aplicar decisoes humanas.")
    identity_reviews_parser = subparsers.add_parser("import-identity-reviews", help="Aplica decisoes humanas da fila de identidade.")
    identity_reviews_parser.add_argument("--input", default="data/reviews/identity_pending_enriched.csv", help="CSV de revisao de identidade.")
    identity_reviews_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    identity_reviews_parser.add_argument("--reviewed-by", required=True, help="Pessoa responsavel pela revisao.")
    identity_reviews_parser.add_argument("--confirm", action="store_true", help="Confirmacao obrigatoria para aplicar decisoes humanas.")
    readiness_parser = subparsers.add_parser("data-readiness-report", help="Gera relatorio de bloqueios de identidade e datas.")
    readiness_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    date_reviews_parser = subparsers.add_parser("import-date-reviews", help="Aplica decisoes humanas da fila de datas sem alterar dados brutos.")
    date_reviews_parser.add_argument("--input", default="data/reviews/date_quality_review.csv", help="CSV de revisao de datas.")
    date_reviews_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    date_reviews_parser.add_argument("--reviewed-by", required=True, help="Pessoa responsavel pela revisao.")
    date_reviews_parser.add_argument("--confirm", action="store_true", help="Confirmacao obrigatoria para aplicar decisoes humanas.")
    duplicate_parser = subparsers.add_parser("duplicate-alerts", help="Gera alertas deterministicos de possiveis duplicidades.")
    duplicate_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    review_progress_parser = subparsers.add_parser("review-progress-report", help="Gera relatorio de progresso das revisoes humanas.")
    review_progress_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    macrocycle_parser = subparsers.add_parser("macrocycle-report", help="Gera relatorio deterministico do macrociclo operacional.")
    macrocycle_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    macrocycle_parser.add_argument("--weeks", type=int, default=6, help="Numero de semanas do macrociclo, entre 1 e 12.")
    search_parser = subparsers.add_parser("search-literature", help="Busca candidatos academicos para temas pendentes.")
    search_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    search_parser.add_argument("--output", default="data/reviews/literature_candidates_crossref.csv", help="CSV de candidatos encontrado.")
    search_parser.add_argument("--provider", default="crossref", choices=["crossref"], help="Provedor academico.")
    search_parser.add_argument("--limit-per-topic", type=int, default=5, help="Maximo de resultados por tema.")
    search_parser.add_argument("--mailto", default=None, help="E-mail opcional para etiqueta polite pool do Crossref.")
    search_parser.add_argument("--confirm", action="store_true", help="Confirmacao obrigatoria para consultar provedor externo.")
    api_parser = subparsers.add_parser("run-api", help="Executa API local FastAPI.")
    api_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    api_parser.add_argument("--host", default="127.0.0.1", help="Host local.")
    api_parser.add_argument("--port", type=int, default=8000, help="Porta local.")
    dashboard_parser = subparsers.add_parser("export-dashboard-data", help="Exporta JSON agregado para o dashboard local.")
    dashboard_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    dashboard_parser.add_argument("--output", default="data/dashboard/dashboard-data.json", help="Arquivo JSON agregado.")
    phase9_gate_parser = subparsers.add_parser("phase9-readiness", help="Executa gate de prontidao da Fase 9.")
    phase9_gate_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")
    phase9_parser = subparsers.add_parser("build-phase9", help="Gera relatorio exploratorio da Fase 9 respeitando o gate.")
    phase9_parser.add_argument("--database", default="data/database/registro_atleta.db", help="Caminho do banco SQLite.")

    args = parser.parse_args(argv)
    if args.command == "audit-sources":
        return audit_sources(Path(args.source_root), Path(args.output), skip_online=args.skip_online)
    if args.command == "sync":
        return sync_sources(Path(args.database))
    if args.command == "build-identity":
        return build_identity_sources(Path(args.database))
    if args.command == "build-domains":
        return build_domain_sources(Path(args.database))
    if args.command == "build-alerts":
        return build_alert_sources(Path(args.database))
    if args.command == "run-pipeline":
        return run_pipeline_sources(Path(args.database))
    if args.command == "nightly-intelligence":
        return nightly_intelligence_sources(
            Path(args.database),
            args.profile,
            args.days,
            args.reference_date,
            args.include_experimental,
            args.dry_run,
        )
    if args.command == "operation-readiness":
        return operation_readiness_sources(Path(args.database), args.keep_last, args.task_name, args.manual)
    if args.command == "weekly-report":
        return weekly_report_sources(Path(args.database))
    if args.command == "weekly-intelligence-report":
        return weekly_intelligence_report_sources(Path(args.database), args.days, args.reference_date)
    if args.command == "status-panel":
        return status_panel_sources(Path(args.database))
    if args.command == "nightly-briefing":
        return nightly_briefing_sources(Path(args.database), args.main_limit, args.reference_date)
    if args.command == "approved-literature-report":
        return approved_literature_report_sources(Path(args.database))
    if args.command == "backups":
        return backup_sources(args.keep_last)
    if args.command == "restore-backup":
        return restore_backup_sources(Path(args.backup), Path(args.database), args.confirm)
    if args.command == "build-llm-literature":
        return build_llm_literature_sources(Path(args.database))
    if args.command == "llm-research-report":
        return llm_research_report_sources(Path(args.database), args.max_queries, args.results_per_query)
    if args.command == "approve-research-report-articles":
        return approve_research_report_article_sources(Path(args.input), Path(args.database), args.reviewed_by, args.notes)
    if args.command == "catalog-literature":
        return catalog_literature_sources(Path(args.input), Path(args.database), args.confirm)
    if args.command == "import-literature-reviews":
        return import_literature_review_sources(
            Path(args.input),
            Path(args.database),
            args.reviewed_by,
            args.confirm,
        )
    if args.command == "import-identity-reviews":
        return import_identity_review_sources(
            Path(args.input),
            Path(args.database),
            args.reviewed_by,
            args.confirm,
        )
    if args.command == "data-readiness-report":
        return data_readiness_report_sources(Path(args.database))
    if args.command == "import-date-reviews":
        return import_date_review_sources(
            Path(args.input),
            Path(args.database),
            args.reviewed_by,
            args.confirm,
        )
    if args.command == "duplicate-alerts":
        return duplicate_alert_sources(Path(args.database))
    if args.command == "review-progress-report":
        return review_progress_report_sources(Path(args.database))
    if args.command == "macrocycle-report":
        return macrocycle_report_sources(Path(args.database), args.weeks)
    if args.command == "search-literature":
        return search_literature_sources(
            Path(args.database),
            Path(args.output),
            args.provider,
            args.limit_per_topic,
            args.confirm,
            args.mailto,
        )
    if args.command == "run-api":
        return run_api_sources(Path(args.database), args.host, args.port)
    if args.command == "export-dashboard-data":
        return export_dashboard_sources(Path(args.database), Path(args.output))
    if args.command == "phase9-readiness":
        return phase9_readiness_sources(Path(args.database))
    if args.command == "build-phase9":
        return build_phase9_sources(Path(args.database))
    parser.error(f"Comando desconhecido: {args.command}")
    return 2


def audit_sources(source_root: Path, output: Path, skip_online: bool = False) -> int:
    source_root = _resolve_from_root(source_root)
    output = _resolve_from_root(output)
    inventories = inventory_historical_files(source_root)
    online_checks = []
    if not skip_online:
        online_checks = [
            check_google_sheet_csv(item["source_id"], item["spreadsheet_id"], item["gid"])
            for item in GOOGLE_SOURCES
        ]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(inventories, online_checks, source_root), encoding="utf-8")

    duplicate_count = len({item.sha256 for item in inventories})
    print("REGISTRO DO ATLETA - AUDITORIA DE FONTES")
    print(f"Arquivos XLSX encontrados: {len(inventories)}")
    print(f"Hashes unicos: {duplicate_count}")
    print(f"Relatorio: {output}")
    return 0


def _resolve_from_root(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sync_sources(database_path: Path) -> int:
    result = sync(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - SINCRONIZACAO")
    print(f"Fontes verificadas: {result.sources_checked}")
    print(f"Snapshots salvos: {result.snapshots_saved}")
    print(f"Registros novos: {result.records_created}")
    print(f"Registros alterados: {result.records_updated}")
    print(f"Registros repetidos ignorados: {result.records_unchanged}")
    print(f"Erros: {result.errors}")
    print(f"Relatorio: {result.report_path}")
    return 0 if result.errors == 0 else 1


def build_identity_sources(database_path: Path) -> int:
    result = build_identity(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - IDENTIDADE")
    print(f"Atletas criados: {result.athletes_created}")
    print(f"Aliases criados: {result.aliases_created}")
    print(f"Memberships criados: {result.memberships_created}")
    print(f"Candidatos criados: {result.candidates_created}")
    print(f"Associados automaticamente: {result.auto_matched}")
    print(f"Pendentes de revisao: {result.pending_review}")
    print(f"Fila de revisao: {result.review_queue_path}")
    print(f"Relatorio: {result.report_path}")
    return 0


def build_domain_sources(database_path: Path) -> int:
    result = build_domains(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - DOMINIOS")
    print(f"PSR criados: {result.psr_created}")
    print(f"PSR atualizados: {result.psr_updated}")
    print(f"PSR sem identidade: {result.psr_skipped_without_identity}")
    print(f"Reports fisio criados: {result.weekly_physio_created}")
    print(f"Reports fisio atualizados: {result.weekly_physio_updated}")
    print(f"Eventos fisio criados: {result.physio_events_created}")
    print(f"Eventos fisio atualizados: {result.physio_events_updated}")
    print(f"Fisio sem identidade: {result.physio_skipped_without_identity}")
    print(f"Avaliacoes criadas: {result.assessments_created}")
    print(f"Avaliacoes atualizadas: {result.assessments_updated}")
    print(f"Metricas de avaliacao criadas: {result.assessment_metrics_created}")
    print(f"Metricas de avaliacao substituidas: {result.assessment_metrics_replaced}")
    print(f"Avaliacoes sem identidade: {result.assessments_skipped_without_identity}")
    print(f"Relatorio: {result.report_path}")
    return 0


def build_alert_sources(database_path: Path) -> int:
    result = build_alerts(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - ALERTAS")
    print(f"Baselines criados: {result.baselines_created}")
    print(f"Alertas criados: {result.alerts_created}")
    print(f"Achados de qualidade criados: {result.quality_findings_created}")
    print(f"Relatorio: {result.report_path}")
    return 0


def run_pipeline_sources(database_path: Path) -> int:
    result = run_operational_pipeline(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - ROTINA OPERACIONAL")
    print(f"Status: {result.status}")
    print(f"Backup: {result.backup_path}")
    for step in result.steps:
        print(f"{step.name}: {step.status} - {step.detail}")
    print(f"Relatorio: {result.report_path}")
    return 0 if result.status in {"success", "success_with_warnings", "degraded"} else 1


def nightly_intelligence_sources(
    database_path: Path,
    profile: str,
    days: int,
    reference_date: str | None,
    include_experimental: bool,
    dry_run: bool,
) -> int:
    try:
        result = run_nightly_intelligence(
            ROOT,
            database_path=_resolve_from_root(database_path),
            profile=profile,
            days=days,
            reference_date=reference_date,
            include_experimental=include_experimental,
            dry_run=dry_run,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Rotina noturna bloqueada: {exc}")
        return 2
    print("REGISTRO DO ATLETA - NIGHTLY INTELLIGENCE PIPELINE")
    print(f"Perfil: {result.profile}")
    print(f"Status: {result.status}")
    for stage in result.stages:
        print(f"[{stage.block}] {stage.title}: {stage.status}")
    if result.summary_path:
        print(f"Resumo: {result.summary_path}")
        print(f"Manifesto: {result.manifest_path}")
        print(f"Log: {result.log_path}")
    return 0 if result.status in {"success", "degraded", "planned"} else 1


def operation_readiness_sources(database_path: Path, keep_last: int, task_name: str, manual: bool) -> int:
    result = build_operational_readiness_report(
        ROOT,
        database_path=_resolve_from_root(database_path),
        retention_limit=keep_last,
        task_name=task_name,
        scheduler_required=not manual,
    )
    print("REGISTRO DO ATLETA - PRONTIDAO OPERACIONAL")
    print(f"Status: {result.status}")
    for check in result.checks:
        print(f"{check.name}: {check.status} - {check.detail}")
    print(f"Relatorio: {result.report_path}")
    return 0 if result.status in {"success", "degraded"} else 1


def weekly_report_sources(database_path: Path) -> int:
    result = build_weekly_report(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - RELATORIO SEMANAL")
    print(f"Alertas abertos: {result.alerts_count}")
    print(f"Identidades pendentes: {result.pending_identity_count}")
    print(f"Achados de qualidade: {result.quality_count}")
    print(f"Relatorio: {result.report_path}")
    return 0


def weekly_intelligence_report_sources(database_path: Path, days: int, reference_date: str | None) -> int:
    result = build_weekly_intelligence_report(
        ROOT,
        database_path=_resolve_from_root(database_path),
        days=days,
        reference_date=reference_date,
    )
    print("REGISTRO DO ATLETA - RELATORIO SEMANAL INTEGRADO")
    print(f"Periodo: {result.period_start} a {result.period_end}")
    print(f"Status LLM: {result.llm_status}")
    print(f"Artigos aprovados incluidos: {result.articles_included}")
    print(f"Markdown: {result.report_path}")
    print(f"JSON: {result.json_path}")
    return 0


def status_panel_sources(database_path: Path) -> int:
    panel_path = build_status_panel(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - STATUS")
    print(f"Painel: {panel_path}")
    return 0


def nightly_briefing_sources(database_path: Path, main_limit: int, reference_date: str | None) -> int:
    result = build_nightly_briefing(
        ROOT,
        database_path=_resolve_from_root(database_path),
        main_limit=main_limit,
        reference_date=reference_date,
    )
    print("REGISTRO DO ATLETA - BRIEFING MATINAL")
    print(f"Status: {result.status}")
    print(f"Itens principais: {result.main_items}")
    print(f"Itens no apendice: {result.appendix_items}")
    print(f"Episodios tocados: {result.episodes_touched}")
    print(f"Markdown: {result.markdown_path}")
    print(f"HTML: {result.html_path}")
    print(f"JSON: {result.json_path}")
    return 0 if result.status in {"success", "success_with_warnings", "degraded"} else 1


def approved_literature_report_sources(database_path: Path) -> int:
    result = build_approved_literature_report(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - LITERATURA APROVADA")
    print(f"Vinculos aprovados: {result.approved_links}")
    print(f"Artigos aprovados: {result.approved_papers}")
    print(f"Relatorio: {result.report_path}")
    return 0


def macrocycle_report_sources(database_path: Path, weeks: int) -> int:
    result = build_macrocycle_report(ROOT, database_path=_resolve_from_root(database_path), weeks=weeks)
    print("REGISTRO DO ATLETA - MACROCICLO OPERACIONAL")
    print(f"Periodo: {result.cycle_start} a {result.cycle_end}")
    print(f"Semanas: {result.weeks}")
    print(f"Carga de decisao: {result.decision_load}")
    print(f"Episodios ativos: {result.active_episodes}")
    print(f"Risco alto: {result.high_episodes}")
    print(f"Markdown: {result.report_path}")
    print(f"JSON: {result.json_path}")
    return 0


def backup_sources(keep_last: int | None) -> int:
    if keep_last is not None:
        removed = prune_backups(ROOT, keep_last=keep_last)
        print("REGISTRO DO ATLETA - BACKUPS")
        print(f"Backups removidos: {len(removed)}")
    backups = list_backups(ROOT)
    print("Backups encontrados:")
    for backup in backups:
        print(f"- {backup} ({backup.stat().st_size} bytes)")
    return 0


def restore_backup_sources(backup_path: Path, database_path: Path, confirm: bool) -> int:
    if not confirm:
        print("Restauracao bloqueada: use --confirm para sobrescrever o banco local.")
        return 2
    report = restore_database(_resolve_from_root(backup_path), _resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - RESTAURACAO")
    print(f"Banco restaurado: {report.database_path}")
    print(f"Integridade SQLite: {report.integrity_check}")
    print(f"Status pos-restore: {report.status}")
    if report.missing_tables:
        print(f"Tabelas obrigatorias ausentes: {', '.join(report.missing_tables)}")
    if report.error_message:
        print(f"Erro: {report.error_message}")
    for table, count in sorted(report.table_counts.items()):
        print(f"{table}: {count}")
    return 0 if report.ok else 1


def build_llm_literature_sources(database_path: Path) -> int:
    result = build_llm_literature(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - LLM E LITERATURA")
    print(f"Topicos criados: {result.topics_created}")
    print(f"Status geracao: {result.generation_status}")
    print(f"Relatorio: {result.report_path}")
    return 0


def llm_research_report_sources(database_path: Path, max_queries: int, results_per_query: int) -> int:
    result = build_llm_research_report(
        ROOT,
        database_path=_resolve_from_root(database_path),
        max_queries=max_queries,
        results_per_query=results_per_query,
    )
    print("REGISTRO DO ATLETA - RELATORIO CIENTIFICO LLM")
    print(f"Modelo: {result.model}")
    print(f"Status chaves: {result.key_generation_status}")
    print(f"Status relatorio: {result.report_generation_status}")
    print(f"Chaves geradas: {len(result.search_queries)}")
    print(f"Artigos candidatos lidos: {result.articles_found}")
    print(f"Relatorio: {result.report_path}")
    return 0 if result.report_generation_status in {"success", "disabled"} else 1


def approve_research_report_article_sources(input_path: Path, database_path: Path, reviewed_by: str, notes: str | None) -> int:
    result = approve_research_report_articles(
        report_path=_resolve_from_root(input_path),
        database_path=_resolve_from_root(database_path),
        reviewed_by=reviewed_by,
        notes=notes,
    )
    print("REGISTRO DO ATLETA - APROVACAO DE ARTIGOS DO RELATORIO LLM")
    print(f"Artigos novos aprovados: {result.approved_articles}")
    print(f"Artigos duplicados reaproveitados: {result.duplicate_articles}")
    print(f"Vinculos aprovados: {result.approved_links}")
    print(f"Linhas invalidas: {result.invalid_rows}")
    return 0 if result.invalid_rows == 0 else 1


def catalog_literature_sources(input_path: Path, database_path: Path, confirm: bool) -> int:
    result = catalog_literature_candidates(
        ROOT,
        csv_path=_resolve_from_root(input_path),
        database_path=_resolve_from_root(database_path),
        confirm=confirm,
    )
    print("REGISTRO DO ATLETA - CATALOGO DE LITERATURA")
    if result.blocked_reason:
        print(result.blocked_reason)
        return 2
    print(f"Artigos importados: {result.imported_papers}")
    print(f"Duplicatas reaproveitadas: {result.duplicate_papers}")
    print(f"Vinculos tema-artigo criados: {result.linked_topics}")
    print(f"Linhas ignoradas: {result.skipped_rows}")
    print(f"Fila de revisao: {result.review_queue_path}")
    return 0


def import_literature_review_sources(input_path: Path, database_path: Path, reviewed_by: str, confirm: bool) -> int:
    result = import_literature_reviews(
        ROOT,
        csv_path=_resolve_from_root(input_path),
        database_path=_resolve_from_root(database_path),
        reviewed_by=reviewed_by,
        confirm=confirm,
    )
    print("REGISTRO DO ATLETA - REVISAO DE LITERATURA")
    if result.blocked_reason:
        print(result.blocked_reason)
        return 2
    print(f"Revisoes aplicadas: {result.applied_reviews}")
    print(f"Linhas ignoradas: {result.skipped_rows}")
    print(f"Linhas invalidas: {result.invalid_rows}")
    print(f"Fila atualizada: {result.review_queue_path}")
    return 0 if result.invalid_rows == 0 else 1


def import_identity_review_sources(input_path: Path, database_path: Path, reviewed_by: str, confirm: bool) -> int:
    result = import_identity_reviews(
        csv_path=_resolve_from_root(input_path),
        database_path=_resolve_from_root(database_path),
        reviewed_by=reviewed_by,
        confirm=confirm,
    )
    print("REGISTRO DO ATLETA - REVISAO DE IDENTIDADE")
    if result.blocked_reason:
        print(result.blocked_reason)
        return 2
    print(f"Revisoes aplicadas: {result.applied_reviews}")
    print(f"Linhas ignoradas: {result.skipped_rows}")
    print(f"Linhas invalidas: {result.invalid_rows}")
    return 0 if result.invalid_rows == 0 else 1


def data_readiness_report_sources(database_path: Path) -> int:
    result = build_data_readiness_report(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - DATA READINESS")
    print(f"Identidades pendentes: {result.pending_identity}")
    print(f"Achados de data: {result.date_findings}")
    print(f"Achados de qualidade abertos: {result.open_quality_findings}")
    print(f"Relatorio: {result.report_path}")
    print(f"Fila identidade: {result.identity_review_path}")
    print(f"Fila datas: {result.date_review_path}")
    return 0


def import_date_review_sources(input_path: Path, database_path: Path, reviewed_by: str, confirm: bool) -> int:
    result = import_date_reviews(
        csv_path=_resolve_from_root(input_path),
        database_path=_resolve_from_root(database_path),
        reviewed_by=reviewed_by,
        confirm=confirm,
    )
    print("REGISTRO DO ATLETA - REVISAO DE DATAS")
    if result.blocked_reason:
        print(result.blocked_reason)
        return 2
    print(f"Revisoes aplicadas: {result.applied_reviews}")
    print(f"Linhas ignoradas: {result.skipped_rows}")
    print(f"Linhas invalidas: {result.invalid_rows}")
    return 0 if result.invalid_rows == 0 else 1


def duplicate_alert_sources(database_path: Path) -> int:
    result = build_duplicate_alerts(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - ALERTAS DE DUPLICACAO")
    print(f"Achados criados: {result.findings_created}")
    print(f"Conflitos de alias: {result.alias_conflicts}")
    print(f"Nomes pendentes repetidos: {result.pending_name_duplicates}")
    print(f"Registros atuais duplicados por hash: {result.source_record_duplicates}")
    print(f"Relatorio: {result.report_path}")
    print(f"Fila de revisao: {result.review_path}")
    return 0


def review_progress_report_sources(database_path: Path) -> int:
    result = build_review_progress_report(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - PROGRESSO DAS REVISOES")
    print(f"Identidades pendentes: {result.pending_identity}")
    print(f"Identidades revisadas: {result.reviewed_identity}")
    print(f"Achados de data abertos: {result.open_date_findings}")
    print(f"Revisoes de data: {result.reviewed_dates}")
    print(f"Duplicatas abertas: {result.open_duplicate_findings}")
    print(f"Revisoes de duplicata: {result.reviewed_duplicates}")
    print(f"Relatorio: {result.report_path}")
    print(f"JSON: {result.json_path}")
    return 0


def search_literature_sources(
    database_path: Path,
    output_path: Path,
    provider: str,
    limit_per_topic: int,
    confirm: bool,
    mailto: str | None,
) -> int:
    result = search_literature_candidates(
        ROOT,
        database_path=_resolve_from_root(database_path),
        output_path=_resolve_from_root(output_path),
        provider=provider,
        limit_per_topic=limit_per_topic,
        confirm=confirm,
        mailto=mailto,
    )
    print("REGISTRO DO ATLETA - BUSCA DE LITERATURA")
    if result.blocked_reason:
        print(result.blocked_reason)
        return 2
    print(f"Temas pesquisados: {result.topics_searched}")
    print(f"Candidatos gravados: {result.candidates_written}")
    print(f"Erros: {result.errors}")
    print(f"CSV de candidatos: {result.output_path}")
    return 0 if result.errors == 0 else 1


def run_api_sources(database_path: Path, host: str, port: int) -> int:
    try:
        import uvicorn
        from registro_atleta.api.app import create_app
    except ImportError:
        print("API indisponivel: instale as dependencias opcionais com `pip install .[api]`.")
        return 2
    try:
        app = create_app(_resolve_from_root(database_path))
    except RuntimeError as exc:
        print(str(exc))
        return 2
    print(f"REGISTRO DO ATLETA - API LOCAL http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
    return 0


def export_dashboard_sources(database_path: Path, output_path: Path) -> int:
    result = export_dashboard_data(ROOT, database_path=_resolve_from_root(database_path), output_path=_resolve_from_root(output_path))
    print("REGISTRO DO ATLETA - DASHBOARD")
    print(f"Atletas: {result.athletes}")
    print(f"Alertas abertos: {result.alerts_open}")
    print(f"Achados de qualidade: {result.quality_open}")
    print(f"JSON: {result.output_path}")
    return 0


def phase9_readiness_sources(database_path: Path) -> int:
    result = assess_phase9_readiness(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - FASE 9 GATE")
    print(f"Status geral: {result.overall_status}")
    print(f"Modelos avancados liberados: {result.models_allowed}")
    for check in result.checks:
        print(f"{check.name}: {check.status} - {check.metric}")
    print(f"Relatorio: {result.report_path}")
    print(f"JSON: {result.json_path}")
    return 0


def build_phase9_sources(database_path: Path) -> int:
    result = build_phase9_exploratory_report(ROOT, database_path=_resolve_from_root(database_path))
    print("REGISTRO DO ATLETA - FASE 9")
    print(f"Status: {result.status}")
    print(f"Modelos avancados liberados: {result.models_allowed}")
    print(f"Gate: {result.readiness_report_path}")
    print(f"Relatorio: {result.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
