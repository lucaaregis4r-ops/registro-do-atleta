from __future__ import annotations

import re
import unicodedata


SECTION_MARKERS = {
    "ALERTA",
    "ALERTAS",
    "ALTA",
    "ATENDIMENTOS",
    "ATLETAS EM TRATAMENTO",
    "CORRELACAO",
    "CORRELACOES",
    "HISTORICO",
    "HISTÓRICO",
    "MEDIA",
    "MEDIANA",
    "MODALIDADE",
    "NOME",
    "PSR",
    "RISCO",
    "ATLETA",
    "CATEGORIA",
    "TRATAMENTO",
    "VARIAVEL",
}


def normalize_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    uppercase = without_accents.upper()
    letters_and_spaces = re.sub(r"[^A-Z0-9 ]+", " ", uppercase)
    return re.sub(r"\s+", " ", letters_and_spaces).strip()


def is_probable_person_name(value: str) -> bool:
    normalized = normalize_name(value)
    if not normalized:
        return False
    if any(marker in normalized for marker in SECTION_MARKERS):
        return False
    if normalized in {"NAO", "NAO SENTI", "NENHUM", "NENHUMA", "SIM"}:
        return False
    if any(char.isdigit() for char in normalized):
        return False
    tokens = normalized.split()
    if len(tokens) < 2:
        return False
    if len(normalized) < 6:
        return False
    return True
