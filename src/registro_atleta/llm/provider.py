from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
import urllib.request


@dataclass(frozen=True)
class LlmResult:
    provider: str
    model: str | None
    status: str
    output_text: str


class DisabledLlmProvider:
    provider = "disabled"
    model = None

    def generate(self, prompt: dict) -> LlmResult:
        return LlmResult(
            provider=self.provider,
            model=self.model,
            status="disabled",
            output_text=_deterministic_summary(prompt),
        )


class OllamaProvider:
    provider = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout_seconds: int | None = 1800) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: dict) -> LlmResult:
        options: dict[str, Any] = {}
        num_predict = os.environ.get("REGISTRO_ATLETA_LLM_NUM_PREDICT")
        if num_predict:
            options["num_predict"] = int(num_predict)
        num_ctx = os.environ.get("REGISTRO_ATLETA_LLM_NUM_CTX")
        if num_ctx:
            options["num_ctx"] = int(num_ctx)
        temperature = os.environ.get("REGISTRO_ATLETA_LLM_TEMPERATURE")
        if temperature:
            options["temperature"] = float(temperature)
        elif "output_schema" in prompt:
            options["temperature"] = 0.1
        payload = {
            "model": self.model,
            "prompt": json.dumps(prompt, ensure_ascii=False),
            "stream": False,
            "keep_alive": os.environ.get("REGISTRO_ATLETA_OLLAMA_KEEP_ALIVE", "0"),
        }
        if "output_schema" in prompt:
            payload["format"] = "json"
        if options:
            payload["options"] = options
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            output_text = str(payload.get("response", "")).strip()
            if not output_text:
                return LlmResult(self.provider, self.model, "failed", "LLM devolveu saida vazia.")
            return LlmResult(self.provider, self.model, "success", output_text)
        except Exception as exc:  # noqa: BLE001 - LLM failure must not break data pipeline.
            return LlmResult(self.provider, self.model, "failed", f"LLM indisponivel: {type(exc).__name__}: {exc}")


def provider_from_env():
    enabled = os.environ.get("REGISTRO_ATLETA_LLM_ENABLED", "").lower() in {"1", "true", "yes", "sim"}
    if not enabled:
        return DisabledLlmProvider()
    provider = os.environ.get("REGISTRO_ATLETA_LLM_PROVIDER", "ollama").lower()
    if provider == "ollama":
        timeout_raw = os.environ.get("REGISTRO_ATLETA_LLM_TIMEOUT_SECONDS", "1800").strip()
        timeout_seconds = None if timeout_raw in {"", "0", "none", "None", "NONE"} else int(timeout_raw)
        return OllamaProvider(
            model=os.environ.get("REGISTRO_ATLETA_OLLAMA_MODEL", "llama3.1"),
            base_url=os.environ.get("REGISTRO_ATLETA_OLLAMA_URL", "http://localhost:11434"),
            timeout_seconds=timeout_seconds,
        )
    return DisabledLlmProvider()


def _deterministic_summary(prompt: dict) -> str:
    summary = prompt.get("summary", {})
    alerts = summary.get("alerts_total", 0)
    quality = summary.get("quality_total", 0)
    topics = prompt.get("topics", [])
    topic_text = ", ".join(topic.get("topic", "") for topic in topics[:5])
    return (
        "Resumo deterministico com LLM desabilitado. "
        f"Alertas abertos: {alerts}. Achados de qualidade: {quality}. "
        f"Temas sugeridos para revisao cientifica: {topic_text or 'nenhum'}."
    )
