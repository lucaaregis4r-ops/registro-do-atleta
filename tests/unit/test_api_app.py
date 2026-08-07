import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest


async def _asgi_request(app, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = urlsplit(path)
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    request_messages = [{"type": "http.request", "body": body, "more_body": False}]
    response_status = 0
    response_body = bytearray()

    async def receive() -> dict:
        return request_messages.pop(0) if request_messages else {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = message["status"]
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": url.path,
            "raw_path": url.path.encode("ascii"),
            "query_string": url.query.encode("ascii"),
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "root_path": "",
        },
        receive,
        send,
    )
    decoded = json.loads(response_body.decode("utf-8")) if response_body else {}
    return response_status, decoded


def test_identity_review_payload_is_read_from_json_body(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from registro_atleta.api.app import create_app

    app = create_app(tmp_path / "registro_atleta.db")
    status, response = asyncio.run(
        _asgi_request(
            app,
            "POST",
            "/identity/reviews",
            {
                "candidate_id": "missing-candidate",
                "decision": "create_new_athlete",
                "reviewed_by": "Teste",
                "new_athlete_name": "Atleta Novo",
                "notes": "teste de contrato",
            },
        )
    )

    assert status == 400
    assert "query.payload" not in json.dumps(response)
    assert response["detail"] == "candidate_id nao encontrado"


def test_openapi_declares_identity_review_request_body(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from registro_atleta.api.app import create_app

    app = create_app(tmp_path / "registro_atleta.db")
    status, schema = asyncio.run(_asgi_request(app, "GET", "/openapi.json"))

    operation = schema["paths"]["/identity/reviews"]["post"]
    assert status == 200
    assert "requestBody" in operation
    assert not any(parameter["name"] == "payload" for parameter in operation.get("parameters", []))
