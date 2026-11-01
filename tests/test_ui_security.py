"""Security checks for the local UI's Host and Origin protections."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "ui"))
import app as ui_module


def request_app(
    method: str, path: str, headers: dict[str, str], body: bytes = b""
) -> int:
    raw_path = path.encode()
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "server": ("127.0.0.1", 8080),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
    }
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(ui_module.app(scope, receive, send))
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


class UISecurityTests(unittest.TestCase):
    def test_rejects_untrusted_host(self) -> None:
        status = request_app("GET", "/api/health", {"host": "attacker.example"})
        self.assertEqual(status, 400)

    def test_rejects_cross_origin_api_request_before_engine_access(self) -> None:
        body = b'{"query":"vehicle history"}'
        with patch.object(
            ui_module.asyncio, "open_unix_connection", create=True
        ) as open_connection:
            status = request_app(
                "POST",
                "/api/ask",
                {
                    "host": "127.0.0.1:8080",
                    "origin": "http://attacker.example",
                    "content-type": "application/json",
                },
                body,
            )
        self.assertEqual(status, 403)
        open_connection.assert_not_called()

    def test_allows_same_origin_and_originless_local_api_clients(self) -> None:
        body = b'{"query":"vehicle history"}'
        for origin in ("http://127.0.0.1:8080", None):
            headers = {
                "host": "127.0.0.1:8080",
                "content-type": "application/json",
            }
            if origin is not None:
                headers["origin"] = origin
            with self.subTest(origin=origin):
                with patch.object(
                    ui_module.asyncio,
                    "open_unix_connection",
                    create=True,
                    side_effect=OSError("no test engine"),
                ) as open_connection:
                    status = request_app("POST", "/api/ask", headers, body)
                self.assertEqual(status, 503)
                open_connection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
