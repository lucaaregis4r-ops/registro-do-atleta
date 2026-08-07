const state = {
  data: null,
  reviewMode: "identity",
  reviewData: {
    identity: [],
    dates: [],
    episodes: [],
    literature: [],
  },
  athletes: [],
  athleteOptionsLoaded: false,
  duplicates: [],
};

const labels = {
  athletes: "Atletas",
  psr_responses: "PSR",
  physio_cases: "Casos fisio",
  physical_assessments: "Avaliações",
  alerts_open: "Alertas abertos",
  alert_episodes_active: "Episódios ativos",
  briefing_main_items: "Briefing principal",
  briefing_appendix_items: "Apêndice",
  quality_open: "Qualidade",
  identity_pending: "Identidade pendente",
  literature_approved: "Literatura aprovada",
};

const reviewCopy = {
  identity: {
    title: "Decisoes de identidade",
    question: "Para cada nome, decida se ele e um atleta ja cadastrado, um atleta novo, ou um registro que nao deve ser vinculado agora.",
    countLabel: "nomes pendentes",
  },
  dates: {
    title: "Decisoes de datas",
    question: "Para cada data suspeita, escolha se existe uma data correta, se o registro deve sair das series temporais, ou se a data deve ser mantida.",
    countLabel: "datas pendentes",
  },
  episodes: {
    title: "Decisoes de acompanhamento",
    question: "Marque se o episodio foi visto, resolvido ou descartado para registrar a revisao operacional.",
    countLabel: "episodios na fila",
  },
  literature: {
    title: "Decisoes de literatura",
    question: "Aprove, rejeite ou envie para revisao antes de usar o artigo como referencia do clube.",
    countLabel: "artigos pendentes",
  },
};

const reviewGuides = {
  identity: [
    "1. Leia o nome bruto, modalidade e categoria.",
    "2. Se ja existir no cadastro, escolha o athlete_id correto e clique em Vincular atleta existente.",
    "3. Se nao existir ainda, clique em Criar novo atleta; o sistema gera um novo OLY-ATH e aproveita modalidade/categoria do candidato.",
    "4. Se estiver errado ou inseguro, clique em Rejeitar/manter sem vinculo.",
  ],
  dates: [
    "1. Veja o valor atual apontado como invalido, futuro ou suspeito.",
    "2. Use data corrigida quando souber a data certa e preencha YYYY-MM-DD.",
    "3. Exclua das series temporais quando a data nao puder ser confiavel.",
    "4. Mantenha como esta apenas quando a data parecer estranha, mas for realmente valida.",
  ],
  episodes: [
    "1. Revise o episodio como acompanhamento operacional, nao como diagnostico clinico.",
    "2. Marque ciente quando a equipe viu e vai acompanhar.",
    "3. Marque resolvido quando o caso deixou de exigir acompanhamento nesta fila.",
    "4. Descarte apenas quando o alerta nao fizer sentido para revisao.",
  ],
  literature: [
    "1. Aprove apenas artigos que a equipe aceita como referencia de apoio.",
    "2. Rejeite quando o tema, metodo ou contexto nao servir para o clube.",
    "3. Use precisa revisao quando depender de leitura tecnica posterior.",
  ],
};

initializeApiBase();

document.getElementById("loadApi").addEventListener("click", () => loadFromApi());
document.getElementById("loadDemo").addEventListener("click", () => loadDemo());
document.getElementById("alertSearch").addEventListener("input", renderAlerts);
document.getElementById("severityFilter").addEventListener("change", renderAlerts);
document.getElementById("athleteSearch").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadAthletes();
});
document.getElementById("loadAthletes").addEventListener("click", () => loadAthletes());

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.view).classList.add("active");
    if (tab.dataset.view === "reviews") loadReviewMode(state.reviewMode);
    if (tab.dataset.view === "athletes") loadAthletes();
  });
}

for (const button of document.querySelectorAll(".mode")) {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.reviewMode = button.dataset.reviewMode;
    loadReviewMode(state.reviewMode);
  });
}

async function loadFromApi() {
  setAppStatus("Conectando na API local...");
  try {
    const response = await fetch(`${apiBase()}/dashboard/summary`);
    if (!response.ok) throw new Error(`API local respondeu ${response.status}`);
    setData(await response.json(), "api");
    await loadReviewProgress();
    setAppStatus("Dados reais carregados da API local.");
    await loadReviewMode(state.reviewMode);
    await loadDuplicateFindings();
  } catch (error) {
    setAppStatus(`Nao consegui carregar a API local: ${error.message}. Rode python -m registro_atleta.cli run-api --port ${window.location.port || "8000"} e abra ${window.location.origin}/dashboard/.`, true);
    throw error;
  }
}

async function loadAthletes() {
  if (!state.data || isDemo()) {
    renderAthletes();
    renderDuplicates();
    return;
  }
  const query = document.getElementById("athleteSearch").value.trim();
  const params = new URLSearchParams({ limit: "120" });
  if (query) params.set("query", query);
  try {
    const response = await fetch(`${apiBase()}/athletes?${params.toString()}`);
    if (!response.ok) throw new Error(`API respondeu ${response.status}`);
    state.athletes = await response.json();
    renderAthleteOptions();
    await loadDuplicateFindings();
    renderAthletes();
    renderDuplicates();
  } catch (error) {
    document.getElementById("athleteCatalog").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function loadDuplicateFindings() {
  if (!state.data || isDemo()) {
    state.duplicates = demoDuplicates();
    return;
  }
  const response = await fetch(`${apiBase()}/quality/duplicates?limit=60&status=open`);
  if (!response.ok) throw new Error(`API respondeu ${response.status}`);
  state.duplicates = await response.json();
}

async function loadReviewProgress() {
  if (!state.data || isDemo()) {
    state.data.review_progress = demoReviewProgress();
    renderReviewProgress();
    return;
  }
  const response = await fetch(`${apiBase()}/quality/review-progress`);
  if (!response.ok) throw new Error(`API respondeu ${response.status}`);
  state.data.review_progress = await response.json();
  renderReviewProgress();
  renderOperationalReport();
}

async function loadDemo() {
  setAppStatus("Carregando demo sintetica somente leitura...");
  let data = demoPayload();
  try {
    const response = await fetch("./public/demo-data.json");
    if (response.ok) data = await response.json();
  } catch {
    data = demoPayload();
  }
  setData(data, "demo");
  state.athletes = demoAthletes();
  renderAthleteOptions();
  setAppStatus("Demo sintetica carregada. Para dados reais e revisoes editaveis, inicie a API local.", true);
  state.reviewData.identity = [
    { candidate_id: "demo-candidate-1", name_raw: "Atleta Demo 03", name_normalized: "ATLETA DEMO 03", sport: "Basquete", category: "Sub 15", confidence: 0.4 },
  ];
  state.reviewData.dates = [
    { finding_id: "demo-date-1", finding_type: "psr_invalid_or_future_date", canonical_name: "Atleta Demo 01", entity_id: "psr-demo-1", evidence_json: "{\"response_date\":\"2099-01-01\"}" },
  ];
  state.reviewData.episodes = state.data.alert_episodes || [];
  state.reviewData.literature = [
    { paper_topic_id: "demo-paper-1", topic: "fadiga", title: "Artigo Demo", human_status: "pending_review", reason_selected: "Exemplo sintético." },
  ];
  renderReviewPanel();
}

function setData(data, source = "api") {
  state.data = data;
  state.data.source = source;
  document.getElementById("generatedAt").textContent = `Gerado em UTC: ${data.generated_at || ""}`;
  renderSummary();
  renderBars("noveltyBars", data.episodes_by_novelty || []);
  renderBars("severityBars", data.episodes_by_severity || data.alerts_by_severity || []);
  renderBars("typeBars", data.alerts_by_type || []);
  renderBars("qualityBars", data.quality_by_type || []);
  renderReviewProgress();
  renderOperationalReport();
  renderMacrocycle();
  populateSeverityFilter();
  renderAlerts();
  renderEpisodes();
}

function renderSummary() {
  const target = document.getElementById("summaryCards");
  target.innerHTML = "";
  for (const [key, value] of Object.entries(state.data.summary || {})) {
    const item = document.createElement("article");
    item.className = "metric";
    item.innerHTML = `<span>${labels[key] || key}</span><strong>${value}</strong>`;
    target.appendChild(item);
  }
}

function renderReviewProgress() {
  const target = document.getElementById("reviewProgress");
  if (!target || !state.data) return;
  const progress = state.data.review_progress || demoReviewProgress();
  const summary = progress.summary || {};
  const cards = [
    {
      label: "Identidade",
      pending: summary.pending_identity,
      reviewed: summary.reviewed_identity,
      detail: topProgressDetail(progress.identity_by_domain, "domain", "pending"),
    },
    {
      label: "Datas",
      pending: summary.open_date_findings,
      reviewed: summary.reviewed_dates,
      detail: topProgressDetail(progress.date_findings_by_type, "finding_type", "open"),
    },
    {
      label: "Duplicatas",
      pending: summary.open_duplicate_findings,
      reviewed: summary.reviewed_duplicates,
      detail: topProgressDetail(progress.duplicate_findings_by_type, "finding_type", "open"),
    },
  ];
  target.innerHTML = cards.map(progressCard).join("");
}

function progressCard(card) {
  const pending = Number(card.pending || 0);
  const reviewed = Number(card.reviewed || 0);
  const total = Math.max(1, pending + reviewed);
  const done = Math.round((reviewed / total) * 100);
  return `<article class="progress-card">
    <div>
      <span>${escapeHtml(card.label)}</span>
      <strong>${escapeHtml(pending)}</strong>
      <p>pendentes</p>
    </div>
    <div class="progress-meter" aria-label="${escapeHtml(done)}% revisado"><span style="width:${done}%"></span></div>
    <footer><strong>${escapeHtml(reviewed)}</strong> revisados - ${escapeHtml(card.detail)}</footer>
  </article>`;
}

function renderOperationalReport() {
  const target = document.getElementById("operationalReport");
  if (!target || !state.data) return;
  const summary = state.data.summary || {};
  const progress = state.data.review_progress || demoReviewProgress();
  const progressSummary = progress.summary || {};
  const mainBriefing = (state.data.latest_briefing_items || []).filter((row) => row.included_in_main_brief).slice(0, 6);
  const qualityRows = (state.data.quality_by_type || []).slice(0, 5);
  const queue = [
    { label: "Identidades", value: progressSummary.pending_identity ?? summary.identity_pending, action: "confirmar vinculos de atletas" },
    { label: "Datas", value: progressSummary.open_date_findings, action: "corrigir ou excluir datas temporais" },
    { label: "Duplicatas", value: progressSummary.open_duplicate_findings, action: "resolver nomes repetidos e achados duplicados" },
    { label: "Episodios ativos", value: summary.alert_episodes_active, action: "acompanhar sinais do briefing" },
  ];

  target.innerHTML = `
    <section class="report-hero">
      <div>
        <span class="eyebrow">Relatorio operacional</span>
        <h2>${escapeHtml(reportHeadline(summary, progressSummary))}</h2>
        <p>${escapeHtml(reportNarrative(summary, progressSummary))}</p>
      </div>
      <div class="report-side">
        <div class="report-stamp">
          <span>Gerado em UTC</span>
          <strong>${escapeHtml(formatDateTime(state.data.generated_at))}</strong>
        </div>
        <div class="report-actions">
          <button type="button" data-report-action="copy">Copiar resumo</button>
          <button class="secondary" type="button" data-report-action="print">Imprimir</button>
        </div>
      </div>
    </section>
    <section class="report-section">
      <div class="report-section-head">
        <div>
          <span class="eyebrow">Fila de decisao</span>
          <h2>O que precisa ser decidido agora</h2>
        </div>
      </div>
      <div class="action-grid">${queue.map(reportActionCard).join("")}</div>
    </section>
    <section class="report-section">
      <div class="report-section-head">
        <div>
          <span class="eyebrow">Briefing principal</span>
          <h2>Principais sinais para a equipe</h2>
        </div>
      </div>
      <div class="report-list">${mainBriefing.length ? mainBriefing.map(reportBriefingItem).join("") : `<div class="empty inline">Nenhum item principal no briefing atual.</div>`}</div>
    </section>
    <section class="report-section">
      <div class="report-section-head">
        <div>
          <span class="eyebrow">Qualidade dos dados</span>
          <h2>Gargalos que bloqueiam analises finas</h2>
        </div>
      </div>
      <div class="quality-list">${qualityRows.length ? qualityRows.map(reportQualityItem).join("") : `<div class="empty inline">Nenhum gargalo de qualidade aberto.</div>`}</div>
    </section>`;
  target.querySelector('[data-report-action="copy"]')?.addEventListener("click", () => copyOperationalReport());
  target.querySelector('[data-report-action="print"]')?.addEventListener("click", () => window.print());
}

function renderMacrocycle() {
  const target = document.getElementById("macrocyclePanel");
  if (!target || !state.data) return;
  const macrocycle = state.data.macrocycle || demoMacrocycle();
  const summary = macrocycle.summary || {};
  const blockers = macrocycle.blockers || {};
  const weeks = macrocycle.weeks || [];
  const alertTypes = macrocycle.top_alert_types || [];
  const episodes = macrocycle.priority_episodes || [];
  target.innerHTML = `
    <section class="macro-hero">
      <div>
        <span class="eyebrow">Macrociclo operacional</span>
        <h2>${escapeHtml(summary.primary_focus || "planejamento do ciclo")}</h2>
        <p>${escapeHtml(summary.cycle_start || "-")} a ${escapeHtml(summary.cycle_end || "-")} - ${escapeHtml(summary.weeks || weeks.length)} semanas</p>
      </div>
      <div class="macro-kpis">
        <div><span>Decisoes</span><strong>${escapeHtml(summary.decision_load || 0)}</strong></div>
        <div><span>Episodios ativos</span><strong>${escapeHtml(summary.active_episodes || 0)}</strong></div>
        <div><span>Risco alto</span><strong>${escapeHtml(summary.high_episodes || 0)}</strong></div>
      </div>
    </section>
    <section class="macro-section">
      <div class="report-section-head">
        <div>
          <span class="eyebrow">Semanas do ciclo</span>
          <h2>Foco por semana</h2>
        </div>
      </div>
      <div class="macro-weeks">${weeks.map(macroWeekCard).join("")}</div>
    </section>
    <div class="macro-columns">
      <section class="macro-section">
        <span class="eyebrow">Bloqueios</span>
        <h2>Antes de evoluir analise</h2>
        <div class="quality-list">
          ${macroBlocker("Identidades", blockers.identity_pending)}
          ${macroBlocker("Datas", blockers.date_findings_open)}
          ${macroBlocker("Duplicatas", blockers.duplicate_findings_open)}
          ${macroBlocker("Qualidade", blockers.quality_open)}
        </div>
      </section>
      <section class="macro-section">
        <span class="eyebrow">Alertas dominantes</span>
        <h2>Temas que puxam o ciclo</h2>
        <div class="quality-list">${alertTypes.length ? alertTypes.map(macroAlertType).join("") : `<div class="empty inline">Sem alertas abertos.</div>`}</div>
      </section>
    </div>
    <section class="macro-section">
      <span class="eyebrow">Atletas para acompanhar</span>
      <h2>Episodios prioritarios</h2>
      <div class="report-list">${episodes.length ? episodes.map(macroEpisodeItem).join("") : `<div class="empty inline">Nenhum episodio ativo prioritario.</div>`}</div>
    </section>`;
}

function macroWeekCard(row) {
  return `<article class="macro-week">
    <span>Semana ${escapeHtml(row.week_index || "")}</span>
    <strong>${escapeHtml(row.phase || "")}</strong>
    <p>${escapeHtml(row.week_start || "")} a ${escapeHtml(row.week_end || "")}</p>
    <small>${escapeHtml(row.goal || "")}</small>
  </article>`;
}

function macroBlocker(label, value) {
  return `<article class="quality-item">
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(value || 0)}</strong>
  </article>`;
}

function macroAlertType(row) {
  return `<article class="quality-item">
    <span>${escapeHtml(row.alert_type || "")}</span>
    <strong>${escapeHtml(row.open_count || 0)}</strong>
  </article>`;
}

function macroEpisodeItem(row) {
  return `<article class="report-item">
    <div>
      <span class="badge ${row.current_severity === "high" ? "danger" : ""}">${escapeHtml(row.current_severity || "-")}</span>
      <strong>${escapeHtml(row.athlete_name || "")}</strong>
      <p>${escapeHtml(row.alert_type || "")} - ${escapeHtml(row.novelty_status || "")} - ultimo sinal ${escapeHtml(row.last_seen_at || "-")}</p>
    </div>
    <div class="report-score">
      <span>Prioridade</span>
      <strong>${escapeHtml(row.priority_score || "-")}</strong>
    </div>
  </article>`;
}

function reportHeadline(summary, progressSummary) {
  const pending = Number(progressSummary.pending_identity ?? summary.identity_pending ?? 0);
  const dates = Number(progressSummary.open_date_findings ?? 0);
  const duplicates = Number(progressSummary.open_duplicate_findings ?? 0);
  if (pending || dates || duplicates) return `${pending + dates + duplicates} decisoes humanas ainda seguram a proxima camada analitica`;
  return "Fila humana zerada para os principais bloqueios operacionais";
}

function reportNarrative(summary, progressSummary) {
  const episodes = Number(summary.alert_episodes_active || 0);
  const alerts = Number(summary.alerts_open || 0);
  const identity = Number(progressSummary.pending_identity ?? summary.identity_pending ?? 0);
  const dates = Number(progressSummary.open_date_findings || 0);
  const duplicates = Number(progressSummary.open_duplicate_findings || 0);
  return `${episodes} episodios ativos e ${alerts} alertas abertos. Antes de liberar analises mais finas, priorize ${identity} identidades, ${dates} datas e ${duplicates} duplicatas.`;
}

function reportActionCard(item) {
  const value = Number(item.value || 0);
  const tone = value > 50 ? "danger" : value > 0 ? "warn" : "ok";
  return `<article class="action-card ${tone}">
    <span>${escapeHtml(item.label)}</span>
    <strong>${escapeHtml(value)}</strong>
    <p>${escapeHtml(item.action)}</p>
  </article>`;
}

function reportBriefingItem(row) {
  const bucket = row.priority_bucket || "briefing";
  return `<article class="report-item">
    <div>
      <span class="badge ${bucket === "new" ? "danger" : ""}">${escapeHtml(bucket)}</span>
      <strong>${escapeHtml(row.headline || row.human_summary || "")}</strong>
      <p>${escapeHtml(row.athlete_name || row.alert_type || row.item_type || "")}</p>
    </div>
    <div class="report-score">
      <span>Prioridade</span>
      <strong>${escapeHtml(row.priority_score || "-")}</strong>
    </div>
  </article>`;
}

function reportQualityItem(row) {
  return `<article class="quality-item">
    <span>${escapeHtml(row.label || "")}</span>
    <strong>${escapeHtml(row.value || 0)}</strong>
  </article>`;
}

async function copyOperationalReport() {
  if (!state.data) return;
  const text = buildOperationalReportText();
  try {
    await navigator.clipboard.writeText(text);
    setAppStatus("Resumo operacional copiado.");
  } catch {
    setAppStatus(text, true);
  }
}

function buildOperationalReportText() {
  const summary = state.data.summary || {};
  const progress = state.data.review_progress || demoReviewProgress();
  const progressSummary = progress.summary || {};
  const mainBriefing = (state.data.latest_briefing_items || []).filter((row) => row.included_in_main_brief).slice(0, 6);
  const qualityRows = (state.data.quality_by_type || []).slice(0, 5);
  const lines = [
    "Registro do Atleta - Relatorio operacional",
    `Gerado em UTC: ${formatDateTime(state.data.generated_at)}`,
    "",
    reportHeadline(summary, progressSummary),
    reportNarrative(summary, progressSummary),
    "",
    "Fila de decisao:",
    `- Identidades: ${progressSummary.pending_identity ?? summary.identity_pending ?? 0}`,
    `- Datas: ${progressSummary.open_date_findings ?? 0}`,
    `- Duplicatas: ${progressSummary.open_duplicate_findings ?? 0}`,
    `- Episodios ativos: ${summary.alert_episodes_active ?? 0}`,
    "",
    "Briefing principal:",
    ...mainBriefing.map((row, index) => `${index + 1}. [${row.priority_bucket || "briefing"}] ${row.headline || row.human_summary || ""}`),
    "",
    "Gargalos de qualidade:",
    ...qualityRows.map((row) => `- ${row.label}: ${row.value}`),
  ];
  return lines.join("\n");
}

function formatDateTime(value) {
  if (!value) return "-";
  return String(value).replace("T", " ").replace("+00:00", "Z");
}

function topProgressDetail(rows = [], labelKey, valueKey) {
  if (!rows.length) return "sem gargalo aberto";
  const first = rows[0];
  return `${first[labelKey]}: ${first[valueKey]}`;
}

function renderBars(targetId, rows) {
  const target = document.getElementById(targetId);
  target.innerHTML = "";
  if (!rows.length) {
    target.innerHTML = `<div class="empty inline">Sem dados para este grupo.</div>`;
    return;
  }
  const max = Math.max(1, ...rows.map((row) => Number(row.value || 0)));
  for (const row of rows) {
    const value = Number(row.value || 0);
    const width = Math.max(2, Math.round((value / max) * 100));
    const item = document.createElement("div");
    item.className = "bar-row";
    item.innerHTML = `<span>${escapeHtml(row.label || "")}</span><div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div><strong>${value}</strong>`;
    target.appendChild(item);
  }
}

function populateSeverityFilter() {
  const select = document.getElementById("severityFilter");
  const selected = select.value;
  const buckets = [...new Set((state.data.latest_briefing_items || []).map((row) => row.priority_bucket).filter(Boolean))].sort();
  select.innerHTML = `<option value="">Todos</option>${buckets.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("")}`;
  select.value = selected;
}

function renderAlerts() {
  if (!state.data) return;
  const search = document.getElementById("alertSearch").value.toLowerCase();
  const bucket = document.getElementById("severityFilter").value;
  const source = state.data.latest_briefing_items || state.data.recent_alerts || [];
  const rows = source.filter((row) => {
    const haystack = `${row.priority_bucket || ""} ${row.headline || ""} ${row.athlete_name || ""} ${row.alert_type || ""} ${row.human_summary || ""}`.toLowerCase();
    return (!search || haystack.includes(search)) && (!bucket || row.priority_bucket === bucket);
  });
  document.getElementById("recentAlerts").innerHTML = `<table><thead><tr><th>#</th><th>Estado</th><th>Prioridade</th><th>Principal</th><th>Resumo</th><th>Referência</th></tr></thead><tbody>${rows.map(briefingRow).join("")}</tbody></table>`;
}

function briefingRow(row) {
  if (row.headline) {
    return `<tr><td>${escapeHtml(row.display_order || "")}</td><td>${escapeHtml(row.priority_bucket || "")}</td><td>${escapeHtml(row.priority_score || "")}</td><td>${row.included_in_main_brief ? "sim" : "não"}</td><td>${escapeHtml(row.headline || "")}</td><td>${escapeHtml(row.episode_id || row.alert_id || row.finding_id || "")}</td></tr>`;
  }
  return `<tr><td></td><td>${escapeHtml(row.alert_type || "")}</td><td>${escapeHtml(row.severity || "")}</td><td></td><td>${escapeHtml(row.human_summary || "")}</td><td>${escapeHtml(row.reference_date || "")}</td></tr>`;
}

function renderEpisodes() {
  if (!state.data) return;
  const rows = state.data.alert_episodes || [];
  document.getElementById("episodeTable").innerHTML = `<table><thead><tr><th>Atleta</th><th>Tipo</th><th>Estado</th><th>Novidade</th><th>Severidade</th><th>Prioridade</th><th>Último sinal</th></tr></thead><tbody>${rows.map(episodeRow).join("")}</tbody></table>`;
}

function episodeRow(row) {
  return `<tr><td>${escapeHtml(row.athlete_name || "")}</td><td>${escapeHtml(row.alert_type || "")}</td><td>${escapeHtml(row.episode_status || "")}</td><td>${escapeHtml(row.novelty_status || "")}</td><td>${escapeHtml(row.current_severity || "")}</td><td>${escapeHtml(row.priority_score || "")}</td><td>${escapeHtml(row.last_seen_at || "")}</td></tr>`;
}

function renderAthletes() {
  const rows = isDemo() ? demoAthletes() : state.athletes;
  const target = document.getElementById("athleteCatalog");
  if (!rows.length) {
    target.innerHTML = `<div class="empty">Nenhum atleta encontrado para esta busca.</div>`;
    return;
  }
  target.innerHTML = `<table class="athlete-table"><thead><tr><th>ID</th><th>Atleta</th><th>Aliases</th><th>Vinculos</th><th>Dados</th></tr></thead><tbody>${rows.map(athleteRow).join("")}</tbody></table>`;
  target.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyText(button.dataset.copy || ""));
  });
}

function athleteRow(row) {
  const aliases = splitList(row.aliases).slice(0, 6);
  const memberships = splitList(row.memberships).filter((item) => item.replace("/", "").trim()).slice(0, 4);
  return `<tr>
    <td><button class="copy-id" data-copy="${escapeHtml(row.athlete_id || "")}" type="button">${escapeHtml(row.athlete_id || "")}</button></td>
    <td><strong>${escapeHtml(row.canonical_name || "")}</strong><span>${escapeHtml(row.normalized_name || "")}</span></td>
    <td>${chips(aliases)}<small>${escapeHtml(row.confirmed_alias_count || 0)} confirmados de ${escapeHtml(row.alias_count || 0)}</small></td>
    <td>${chips(memberships)}</td>
    <td><span class="mini-stat">PSR ${escapeHtml(row.psr_count || 0)}</span><span class="mini-stat">Fisio ${escapeHtml(row.physio_case_count || 0)}</span><span class="mini-stat">Aval. ${escapeHtml(row.assessment_count || 0)}</span></td>
  </tr>`;
}

function renderDuplicates() {
  const rows = isDemo() ? demoDuplicates() : state.duplicates;
  const target = document.getElementById("duplicatePanel");
  if (!rows.length) {
    target.innerHTML = `<div class="empty">Nenhuma duplicidade aberta no momento.</div>`;
    return;
  }
  target.innerHTML = rows.map((row, index) => duplicateCard(row, index)).join("");
  target.querySelectorAll("[data-duplicate-action]").forEach((button) => button.addEventListener("click", () => submitDuplicateReview(button)));
}

function duplicateCard(row, index) {
  const evidence = safeJson(row.evidence_json);
  return `<article class="review-card decision-card duplicate-card">
    <div class="review-card-head">
      <div>
        <span class="badge warn">Duplicata</span>
        <strong>${escapeHtml(row.entity_id || evidence.name_normalized || evidence.alias_normalized || "achado")}</strong>
        <p>${escapeHtml(row.human_summary || row.finding_type || "")}</p>
      </div>
      <div class="decision-box warn">
        <span>Severidade</span>
        <strong>${escapeHtml(row.severity || "-")}</strong>
      </div>
    </div>
    <div class="evidence-grid">
      <div><span>Tipo</span><strong>${escapeHtml(row.finding_type || "-")}</strong></div>
      <div><span>Total</span><strong>${escapeHtml(evidence.candidate_count || evidence.athlete_count || evidence.record_count || "-")}</strong></div>
      <div><span>Fontes</span><strong>${escapeHtml(evidence.source_count || evidence.source_id || "-")}</strong></div>
    </div>
    <div class="decision-help">
      <strong>Como decidir</strong>
      <p>Resolvido fecha este achado porque voce ja tratou a fila. Nao e duplicata confirma que os nomes/registros parecem repetidos, mas sao diferentes. Manter pendente deixa para investigar depois.</p>
    </div>
    <div class="review-fields">
      <label>O que voce decidiu?<select data-field="duplicate_decision" data-index="${index}"><option value="mark_reviewed">Resolvido: ja tratei este achado</option><option value="not_duplicate">Nao e duplicata: sao pessoas/registros diferentes</option><option value="needs_follow_up">Manter pendente: preciso conferir depois</option></select><small>Essa decisao fica auditada e nao altera planilha bruta.</small></label>
      <label>Por que?<input data-field="notes" data-index="${index}" placeholder="ex.: nomes iguais, mas atletas diferentes"><small>Escreva uma frase curta para auditoria.</small></label>
    </div>
    <div class="row-actions"><button data-duplicate-action="review" data-index="${index}" type="button">Registrar decisao</button></div>
    <details><summary>IDs relacionados</summary><code>${escapeHtml(duplicateEvidenceText(evidence))}</code></details>
  </article>`;
}

async function loadReviewMode(mode) {
  setNotice("");
  if (!state.data) return;
  if (isDemo()) {
    renderReviewPanel();
    return;
  }
  const endpoints = {
    identity: "/identity/pending?limit=30",
    dates: "/quality/dates?limit=30",
    episodes: "/alert-episodes?episode_status=active&limit=30",
    literature: "/literature/pending?limit=30",
  };
  try {
    const response = await fetch(`${apiBase()}${endpoints[mode]}`);
    if (!response.ok) throw new Error(`API respondeu ${response.status}`);
    state.reviewData[mode] = await response.json();
    if (mode === "identity") await ensureAthleteOptions();
    renderReviewPanel();
  } catch (error) {
    setNotice(error.message, true);
  }
}

async function ensureAthleteOptions() {
  if (isDemo()) {
    state.athletes = demoAthletes();
    renderAthleteOptions();
    return;
  }
  if (state.athleteOptionsLoaded && state.athletes.length) return;
  const response = await fetch(`${apiBase()}/athletes?limit=500`);
  if (!response.ok) throw new Error(`API respondeu ${response.status}`);
  state.athletes = await response.json();
  state.athleteOptionsLoaded = true;
  renderAthleteOptions();
}

function renderAthleteOptions() {
  const target = document.getElementById("athleteOptions");
  if (!target) return;
  const rows = state.athletes.length ? state.athletes : demoAthletes();
  target.innerHTML = rows.map((row) => `<option value="${escapeHtml(row.athlete_id || "")}" label="${escapeHtml(row.canonical_name || "")}"></option>`).join("");
}

function renderReviewPanel() {
  const rows = state.reviewData[state.reviewMode] || [];
  const target = document.getElementById("reviewPanel");
  renderReviewSummary(rows);
  if (!rows.length) {
    target.innerHTML = `<div class="empty">Nenhum item nesta fila.</div>`;
    return;
  }
  target.innerHTML = rows.map((row, index) => reviewCard(state.reviewMode, row, index)).join("");
  target.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => submitReview(button)));
}

function renderReviewSummary(rows) {
  const target = document.getElementById("reviewSummary");
  const copy = reviewCopy[state.reviewMode];
  const pendingFromSummary = {
    identity: state.data?.summary?.identity_pending,
    dates: qualityCount("psr_invalid_or_future_date"),
    episodes: state.data?.summary?.alert_episodes_active,
    literature: Math.max(0, (state.reviewData.literature || rows).length),
  }[state.reviewMode];
  target.innerHTML = `<section class="review-brief">
    <div>
      <span class="eyebrow">${escapeHtml(copy.title)}</span>
      <h2>${escapeHtml(copy.question)}</h2>
      <ol class="decision-guide">
        ${(reviewGuides[state.reviewMode] || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ol>
    </div>
    <div class="review-kpis">
      <div><strong>${escapeHtml(rows.length)}</strong><span>carregados agora</span></div>
      <div><strong>${escapeHtml(pendingFromSummary ?? "-")}</strong><span>${escapeHtml(copy.countLabel)}</span></div>
    </div>
  </section>`;
}

function qualityCount(findingType) {
  const row = (state.data?.quality_by_type || []).find((item) => item.label === findingType);
  return row ? row.value : 0;
}

function reviewCard(mode, row, index) {
  if (mode === "identity") return identityCard(row, index);
  if (mode === "dates") return dateCard(row, index);
  if (mode === "episodes") return episodeReviewCard(row, index);
  return literatureCard(row, index);
}


function legacyEpisodeReviewCard(row, index) {
  const evidence = safeJson(row.evidence_json);
  return `<article class="review-card">
    <div><span class="badge ${row.current_severity === "high" ? "danger" : ""}">Episódio</span><strong>${escapeHtml(row.canonical_name || row.athlete_name || "")}</strong><p>${escapeHtml(row.alert_type || "")} · ${escapeHtml(row.novelty_status || "")} · prioridade ${escapeHtml(row.priority_score || "")}</p></div>
    <div class="review-fields">
      <label>Decisão<select data-field="review_status" data-index="${index}"><option value="acknowledged">ciente</option><option value="resolved">resolvido</option><option value="dismissed">descartar</option></select></label>
      <label>Notas<input data-field="notes" data-index="${index}" placeholder="observação"></label>
    </div>
    <div class="row-actions"><button data-action="episode-apply" data-index="${index}" data-alert="${escapeHtml(evidence.representative_alert_id || "")}" type="button">Aplicar</button></div>
    <code>${escapeHtml(row.episode_id || "")}</code>
  </article>`;
}

function identityCard(row, index) {
  const confidence = Number(row.confidence || 0);
  return `<article class="review-card decision-card">
    <div class="review-card-head">
      <div>
        <span class="badge">Identidade</span>
        <strong>${escapeHtml(row.name_raw || "")}</strong>
        <p>${escapeHtml(row.sport || "Sem modalidade")} ${row.category ? `- ${escapeHtml(row.category)}` : ""}</p>
      </div>
      <div class="decision-box">
        <span>Decisao humana</span>
        <strong>Ja existe no cadastro?</strong>
      </div>
    </div>
    <div class="decision-help">
      <strong>Vincular existente</strong>
      <p>Use quando este nome e uma grafia/apelido de um atleta que ja aparece na aba Atletas. Isso cria alias auditado.</p>
      <strong>Criar novo atleta</strong>
      <p>Use quando voce sabe que ele ainda nao esta cadastrado. O sistema cria um novo ID e grava modalidade/categoria deste card quando existirem.</p>
      <strong>Rejeitar/manter sem vinculo</strong>
      <p>Use quando a sugestao esta errada, quando ha homonimo, ou quando voce nao tem seguranca suficiente.</p>
    </div>
    <div class="evidence-grid">
      <div><span>Nome normalizado</span><strong>${escapeHtml(row.name_normalized || "-")}</strong></div>
      <div><span>Confianca</span><strong>${Math.round(confidence * 100)}%</strong></div>
      <div><span>ID sugerido</span><strong>${escapeHtml(row.proposed_athlete_id || "sem sugestao")}</strong></div>
    </div>
    <div class="review-fields">
      <label>ID existente (nao use para atleta novo)<input data-field="selected_athlete_id" data-index="${index}" list="athleteOptions" value="${escapeHtml(row.proposed_athlete_id || "")}" placeholder="Preencha somente se ja existir"><small>Para criar um atleta novo, este campo pode ficar vazio.</small></label>
      <label>Nome do novo atleta<input data-field="new_athlete_name" data-index="${index}" value="${escapeHtml(row.name_raw || "")}" placeholder="Nome completo se souber"><small>Ao clicar em Criar novo atleta, o sistema gera automaticamente o proximo ID OLY-ATH.</small></label>
      <label>Por que?<input data-field="notes" data-index="${index}" placeholder="ex.: novo atleta Sub-17; ainda nao estava no cadastro"><small>Exemplos: apelido conhecido, atleta novo, sugestao insegura.</small></label>
    </div>
    <div class="row-actions">
      <button data-action="identity-confirm" data-index="${index}" type="button">Vincular atleta existente</button>
      <button data-action="identity-create" data-index="${index}" type="button">Criar novo atleta</button>
      <button class="secondary" data-action="identity-reject" data-index="${index}" type="button">Rejeitar/manter sem vinculo</button>
    </div>
    <details><summary>Rastro tecnico</summary><code>${escapeHtml(shortId(row.candidate_id))}</code></details>
  </article>`;
}

function dateCard(row, index) {
  const evidence = safeJson(row.evidence_json);
  return `<article class="review-card decision-card">
    <div class="review-card-head">
      <div>
        <span class="badge warn">Data</span>
        <strong>${escapeHtml(row.canonical_name || "Sem atleta")}</strong>
        <p>${escapeHtml(row.finding_type || "")}</p>
      </div>
      <div class="decision-box warn">
        <span>Valor atual</span>
        <strong>${escapeHtml(evidence.response_date || "sem data")}</strong>
      </div>
    </div>
    <div class="evidence-grid">
      <div><span>Severidade</span><strong>${escapeHtml(row.severity || "-")}</strong></div>
      <div><span>Entidade</span><strong>${escapeHtml(shortId(row.entity_id))}</strong></div>
      <div><span>Fonte</span><strong>${escapeHtml(row.source_id || "nao informada")}</strong></div>
    </div>
    <div class="decision-help">
      <strong>Escolha uma das tres</strong>
      <p><b>Usar data corrigida</b>: voce sabe a data certa e vai preencher YYYY-MM-DD. <b>Excluir das series</b>: a data nao e confiavel para tendencia. <b>Manter</b>: a data e incomum, mas valida.</p>
    </div>
    <div class="review-fields three">
      <label>O que fazer com esta data?<select data-field="decision" data-index="${index}"><option value="use_corrected_date">Usar data corrigida</option><option value="exclude_from_temporal">Excluir das series temporais</option><option value="keep_as_is">Manter como esta</option></select><small>A fonte bruta nao sera alterada.</small></label>
      <label>Data corrigida<input data-field="corrected_date" data-index="${index}" placeholder="YYYY-MM-DD"><small>Preencha so se escolheu usar data corrigida.</small></label>
      <label>Por que?<input data-field="notes" data-index="${index}" placeholder="ex.: data real no formulario original"><small>Explique o criterio em uma frase.</small></label>
    </div>
    <div class="row-actions"><button data-action="date-apply" data-index="${index}" type="button">Registrar decisao</button></div>
    <details><summary>Rastro tecnico</summary><code>${escapeHtml(shortId(row.finding_id))}</code></details>
  </article>`;
}

function episodeReviewCard(row, index) {
  const evidence = safeJson(row.evidence_json);
  return `<article class="review-card decision-card">
    <div class="review-card-head">
      <div>
        <span class="badge ${row.current_severity === "high" ? "danger" : ""}">Episodio</span>
        <strong>${escapeHtml(row.canonical_name || row.athlete_name || "")}</strong>
        <p>${escapeHtml(row.alert_type || "")}</p>
      </div>
      <div class="decision-box ${row.current_severity === "high" ? "danger" : ""}">
        <span>Prioridade</span>
        <strong>${escapeHtml(row.priority_score || "-")}</strong>
      </div>
    </div>
    <div class="evidence-grid">
      <div><span>Novidade</span><strong>${escapeHtml(row.novelty_status || "-")}</strong></div>
      <div><span>Severidade atual</span><strong>${escapeHtml(row.current_severity || "-")}</strong></div>
      <div><span>Ocorrencias</span><strong>${escapeHtml(row.occurrence_count || "-")}</strong></div>
      <div><span>Ultimo sinal</span><strong>${escapeHtml(row.last_seen_at || "-")}</strong></div>
    </div>
    <div class="review-fields">
      <label>Decisao<select data-field="review_status" data-index="${index}"><option value="acknowledged">ciente, acompanhar</option><option value="resolved">resolvido</option><option value="dismissed">descartar este alerta</option></select></label>
      <label>Justificativa<input data-field="notes" data-index="${index}" placeholder="observacao para auditoria"></label>
    </div>
    <div class="row-actions"><button data-action="episode-apply" data-index="${index}" data-alert="${escapeHtml(evidence.representative_alert_id || "")}" type="button">Registrar acompanhamento</button></div>
    <details><summary>Rastro tecnico</summary><code>${escapeHtml(shortId(row.episode_id))}</code></details>
  </article>`;
}

function literatureCard(row, index) {
  return `<article class="review-card decision-card">
    <div class="review-card-head">
      <div>
        <span class="badge">Literatura</span>
        <strong>${escapeHtml(row.title || "")}</strong>
        <p>${escapeHtml(row.topic || "")} - ${escapeHtml(row.journal || "sem periodico")}</p>
      </div>
      <div class="decision-box">
        <span>Status atual</span>
        <strong>${escapeHtml(row.human_status || "-")}</strong>
      </div>
    </div>
    <div class="evidence-grid">
      <div><span>Ano</span><strong>${escapeHtml(row.publication_year || "-")}</strong></div>
      <div><span>Relevancia</span><strong>${escapeHtml(row.relevance_score || "-")}</strong></div>
      <div><span>DOI</span><strong>${escapeHtml(row.doi || "sem DOI")}</strong></div>
    </div>
    <p class="review-reason">${escapeHtml(row.reason_selected || "")}</p>
    <div class="review-fields">
      <label>Decisao<select data-field="decision" data-index="${index}"><option value="approved">aprovar para uso</option><option value="rejected">rejeitar</option><option value="needs_revision">precisa revisao</option></select></label>
      <label>Justificativa<input data-field="notes" data-index="${index}" placeholder="motivo cientifico ou operacional"></label>
    </div>
    <div class="row-actions"><button data-action="literature-apply" data-index="${index}" type="button">Registrar avaliacao</button></div>
    <details><summary>Rastro tecnico</summary><code>${escapeHtml(shortId(row.paper_topic_id))}</code></details>
  </article>`;
}

async function submitReview(button) {
  if (isDemo()) {
    setNotice("A demo é somente leitura. Conecte a API local para gravar revisões.", true);
    return;
  }
  const reviewer = document.getElementById("reviewerName").value.trim();
  if (!reviewer) {
    setNotice("Informe o responsável antes de aplicar a revisão.", true);
    return;
  }
  const index = Number(button.dataset.index);
  const mode = state.reviewMode;
  const row = state.reviewData[mode][index];
  const payload = buildPayload(button.dataset.action, row, index, reviewer, button);
  if (!payload) return;
  const endpoint = actionEndpoint(button.dataset.action);
  try {
    const response = await fetch(`${apiBase()}${endpoint}`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(apiErrorMessage(error, response.status));
    }
    setNotice("Revisão aplicada.");
    await refreshAfterReview(mode);
  } catch (error) {
    setNotice(error.message, true);
  }
}

async function submitDuplicateReview(button) {
  if (isDemo()) {
    setAppStatus("A demo e somente leitura. Conecte a API local para registrar duplicatas.", true);
    return;
  }
  const reviewer = document.getElementById("reviewerName").value.trim();
  if (!reviewer) {
    setAppStatus("Informe o responsavel antes de registrar a decisao de duplicata.", true);
    return;
  }
  const index = Number(button.dataset.index);
  const row = state.duplicates[index];
  const fields = fieldsFor(index, button.closest("article"));
  try {
    const response = await fetch(`${apiBase()}/quality/duplicate-reviews`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        finding_id: row.finding_id,
        decision: fields.duplicate_decision,
        reviewed_by: reviewer,
        notes: fields.notes,
      }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(apiErrorMessage(error, response.status));
    }
    setAppStatus("Decisao de duplicata registrada.");
    await loadDuplicateFindings();
    renderDuplicates();
  } catch (error) {
    setAppStatus(error.message, true);
  }
}

function buildPayload(action, row, index, reviewer, button) {
  const fields = fieldsFor(index, button.closest("article"));
  if (action === "identity-confirm") {
    if (!fields.selected_athlete_id) {
      setNotice("Para vincular a atleta existente, escolha primeiro o ID do atleta.", true);
      return null;
    }
    return { candidate_id: row.candidate_id, decision: "confirm_match", reviewed_by: reviewer, selected_athlete_id: fields.selected_athlete_id, notes: fields.notes };
  }
  if (action === "identity-create") {
    if (!fields.new_athlete_name) {
      setNotice("Para criar novo atleta, confirme o nome que sera cadastrado.", true);
      return null;
    }
    return { candidate_id: row.candidate_id, decision: "create_new_athlete", reviewed_by: reviewer, new_athlete_name: fields.new_athlete_name, notes: fields.notes };
  }
  if (action === "identity-reject") return { candidate_id: row.candidate_id, decision: "reject_match", reviewed_by: reviewer, notes: fields.notes };
  if (action === "date-apply") {
    if (fields.decision === "use_corrected_date" && !isIsoDate(fields.corrected_date || "")) {
      setNotice("Para usar data corrigida, preencha a data no formato YYYY-MM-DD.", true);
      return null;
    }
    return { finding_id: row.finding_id, decision: fields.decision, reviewed_by: reviewer, corrected_date: fields.corrected_date || null, notes: fields.notes };
  }
  if (action === "episode-apply") {
    const alertId = button.dataset.alert;
    if (!alertId) {
      setNotice("Episódio sem alerta representativo.", true);
      return null;
    }
    return { alert_id: alertId, review_status: fields.review_status, reviewed_by: reviewer, notes: fields.notes };
  }
  return { paper_topic_id: row.paper_topic_id, decision: fields.decision, reviewed_by: reviewer, notes: fields.notes };
}

function isIsoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function apiErrorMessage(error, status) {
  const detail = error?.detail;
  if (!detail) return `API respondeu ${status}`;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const message = detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.join(".") : "";
      return [location, item.msg || item.message || JSON.stringify(item)].filter(Boolean).join(": ");
    }).join(" | ");
    if (message.includes("create_new_athlete")) {
      return `${message}. A API local parece estar em versao antiga; reinicie o run-api e recarregue o dashboard com Ctrl+F5.`;
    }
    return message;
  }
  if (typeof detail === "object") {
    if (detail.msg || detail.message) return detail.msg || detail.message;
    return JSON.stringify(detail);
  }
  return String(detail);
}

async function refreshAfterReview(mode) {
  if (!isDemo()) {
    const summaryResponse = await fetch(`${apiBase()}/dashboard/summary`);
    if (summaryResponse.ok) state.data = await summaryResponse.json();
  }
  await loadReviewMode(mode);
}

function fieldsFor(index, root = document) {
  const values = {};
  root.querySelectorAll(`[data-index="${index}"]`).forEach((item) => {
    if (item.dataset.field) values[item.dataset.field] = item.value;
  });
  return values;
}

function actionEndpoint(action) {
  if (action.startsWith("identity")) return "/identity/reviews";
  if (action.startsWith("date")) return "/quality/date-reviews";
  if (action.startsWith("episode")) return "/alerts/reviews";
  return "/literature/reviews";
}

function apiBase() {
  return document.getElementById("apiBase").value.replace(/\/$/, "");
}

function initializeApiBase() {
  const input = document.getElementById("apiBase");
  if (!window.location.protocol.startsWith("http")) return;
  if (!input.value || input.value === "http://127.0.0.1:8000") {
    input.value = window.location.origin;
  }
}

function apiHeaders() {
  const headers = { "Content-Type": "application/json" };
  const token = document.getElementById("apiToken").value.trim();
  if (token) headers["X-Registro-Atleta-Token"] = token;
  return headers;
}

function isDemo() {
  return state.data?.source === "demo" || state.data?.generated_at === "2026-07-14T00:00:00Z";
}

function setAppStatus(message, isWarning = false) {
  const target = document.getElementById("appStatus");
  target.textContent = message;
  target.className = `app-status ${isWarning ? "warning" : ""}`;
}

function setNotice(message, isError = false) {
  const target = document.getElementById("reviewStatus");
  target.textContent = message;
  target.className = `notice ${isError ? "error" : ""}`;
}

function safeJson(value) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

function splitList(value) {
  if (!value) return [];
  return String(value).split(",").map((item) => item.trim()).filter(Boolean);
}

function chips(items) {
  if (!items.length) return `<span class="muted">-</span>`;
  return `<div class="chips">${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
}

async function copyText(value) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    setAppStatus(`ID copiado: ${value}`);
  } catch {
    setAppStatus(`ID para copiar: ${value}`, true);
  }
}

function duplicateEvidenceText(evidence) {
  const parts = [
    ...(evidence.athlete_ids || []),
    ...(evidence.candidate_ids || []),
    ...(evidence.source_record_ids || []),
  ];
  return parts.length ? parts.join(" | ") : JSON.stringify(evidence);
}

function shortId(value) {
  if (!value) return "-";
  const text = String(value);
  return text.length > 14 ? `${text.slice(0, 8)}...${text.slice(-4)}` : text;
}

function demoAthletes() {
  return [
    { athlete_id: "OLY-ATH-DEMO01", canonical_name: "Atleta Demo 01", normalized_name: "ATLETA DEMO 01", alias_count: 2, confirmed_alias_count: 1, aliases: "Atleta Demo 01, Demo 01", memberships: "Basquete / Sub 15", psr_count: 12, physio_case_count: 1, assessment_count: 2 },
    { athlete_id: "OLY-ATH-DEMO02", canonical_name: "Atleta Demo 02", normalized_name: "ATLETA DEMO 02", alias_count: 1, confirmed_alias_count: 1, aliases: "Atleta Demo 02", memberships: "Volei / Sub 17", psr_count: 6, physio_case_count: 0, assessment_count: 1 },
  ];
}

function demoDuplicates() {
  return [
    { finding_id: "duplicate-demo-1", finding_type: "duplicate_pending_identity_name", entity_id: "ATLETA DEMO", severity: "medium", human_summary: "Nome pendente repetido em 2 candidatos.", evidence_json: "{\"candidate_count\":2,\"source_count\":2,\"candidate_ids\":[\"demo-c1\",\"demo-c2\"]}" },
  ];
}

function demoReviewProgress() {
  return {
    generated_at: "2026-07-14T00:00:00Z",
    summary: {
      pending_identity: 6,
      reviewed_identity: 2,
      open_date_findings: 1,
      reviewed_dates: 1,
      open_duplicate_findings: 1,
      reviewed_duplicates: 0,
    },
    identity_by_domain: [{ domain: "demo", pending: 6 }],
    date_findings_by_type: [{ finding_type: "psr_invalid_or_future_date", severity: "high", open: 1 }],
    duplicate_findings_by_type: [{ finding_type: "duplicate_pending_identity_name", severity: "medium", open: 1 }],
  };
}

function demoMacrocycle() {
  return {
    summary: {
      cycle_start: "2026-07-13",
      cycle_end: "2026-08-23",
      weeks: 6,
      decision_load: 8,
      active_episodes: 2,
      high_episodes: 1,
      primary_focus: "saneamento de decisoes humanas",
    },
    blockers: {
      identity_pending: 6,
      date_findings_open: 1,
      duplicate_findings_open: 1,
      quality_open: 3,
    },
    top_alert_types: [
      { alert_type: "psr_high_pain", open_count: 1 },
      { alert_type: "physio_training_restriction", open_count: 1 },
    ],
    priority_episodes: [
      { athlete_name: "Atleta Demo 01", alert_type: "psr_high_pain", current_severity: "high", novelty_status: "new", priority_score: 91, last_seen_at: "2026-07-14" },
    ],
    weeks: [
      { week_index: 1, week_start: "2026-07-13", week_end: "2026-07-19", phase: "Diagnostico", goal: "resolver identidades pendentes antes de analises por atleta" },
      { week_index: 2, week_start: "2026-07-20", week_end: "2026-07-26", phase: "Estabilizacao", goal: "corrigir datas que bloqueiam series temporais" },
      { week_index: 3, week_start: "2026-07-27", week_end: "2026-08-02", phase: "Ajuste de carga", goal: "fechar duplicatas e conflitos de nomes" },
      { week_index: 4, week_start: "2026-08-03", week_end: "2026-08-09", phase: "Reavaliacao", goal: "conferir resposta dos casos e necessidade de avaliacao" },
      { week_index: 5, week_start: "2026-08-10", week_end: "2026-08-16", phase: "Consolidacao", goal: "reduzir alertas recorrentes e documentar decisoes" },
      { week_index: 6, week_start: "2026-08-17", week_end: "2026-08-23", phase: "Fechamento", goal: "preparar relatorio do ciclo e proximos bloqueios" },
    ],
  };
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function demoPayload() {
  return {
    generated_at: "2026-07-14T00:00:00Z",
    summary: {
      athletes: 2,
      psr_responses: 18,
      physio_cases: 2,
      physical_assessments: 4,
      alerts_open: 2,
      alert_episodes_active: 2,
      briefing_main_items: 2,
      briefing_appendix_items: 0,
      quality_open: 1,
      identity_pending: 1,
      literature_approved: 1,
    },
    episodes_by_novelty: [
      { label: "new", value: 1 },
      { label: "persistent", value: 1 },
    ],
    episodes_by_severity: [
      { label: "high", value: 1 },
      { label: "medium", value: 1 },
    ],
    alerts_by_type: [
      { label: "psr_high_pain", value: 1 },
      { label: "physio_training_restriction", value: 1 },
    ],
    quality_by_type: [
      { label: "psr_invalid_or_future_date", value: 1 },
    ],
    latest_briefing_items: [
      { display_order: 1, priority_bucket: "new", priority_score: 91, included_in_main_brief: true, headline: "Novo: Atleta Demo 01 - psr_high_pain (high).", episode_id: "demo-episode-1" },
      { display_order: 2, priority_bucket: "persistent", priority_score: 70, included_in_main_brief: true, headline: "Persistente: Atleta Demo 02 - physio_training_restriction (medium).", episode_id: "demo-episode-2" },
    ],
    alert_episodes: [
      { episode_id: "demo-episode-1", athlete_name: "Atleta Demo 01", alert_type: "psr_high_pain", episode_status: "active", novelty_status: "new", current_severity: "high", priority_score: 91, last_seen_at: "2026-07-14" },
      { episode_id: "demo-episode-2", athlete_name: "Atleta Demo 02", alert_type: "physio_training_restriction", episode_status: "active", novelty_status: "persistent", current_severity: "medium", priority_score: 70, last_seen_at: "2026-07-14" },
    ],
    macrocycle: demoMacrocycle(),
  };
}

if (window.location.protocol.startsWith("http")) {
  loadFromApi().catch(() => loadDemo());
} else {
  loadDemo();
}
