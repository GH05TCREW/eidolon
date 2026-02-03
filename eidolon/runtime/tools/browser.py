from __future__ import annotations

from contextlib import suppress
from typing import Any

import httpx

from eidolon.runtime.tools.base import Tool


class BrowserTool(Tool):
    name = "browser"
    description = "Issue HTTP requests against web endpoints."
    sandbox_execution = True

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to request",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS)",
                },
                "headers": {
                    "type": "object",
                    "description": "Optional request headers",
                },
                "params": {
                    "type": "object",
                    "description": "Optional query parameters",
                },
                "json": {
                    "type": "object",
                    "description": "Optional JSON body",
                },
                "data": {
                    "type": "string",
                    "description": "Optional form/body payload as a string",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds",
                },
                "follow_redirects": {
                    "type": "boolean",
                    "description": "Follow HTTP redirects",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max response characters to return",
                },
            },
            "required": ["url"],
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = payload.get("url")
        if not url:
            return {"error": "url is required"}

        method = str(payload.get("method", "GET")).upper()
        headers = payload.get("headers") or {}
        params = payload.get("params") or {}
        json_body = payload.get("json")
        data = payload.get("data")
        timeout = payload.get("timeout", 10)
        follow_redirects = bool(payload.get("follow_redirects", True))
        max_chars_raw = payload.get("max_chars", 2000)
        try:
            max_chars = int(max_chars_raw)
        except (TypeError, ValueError):
            max_chars = 2000

        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            return {"error": f"unsupported method {method}"}

        try:
            with httpx.Client(timeout=timeout, follow_redirects=follow_redirects) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=data,
                )
        except httpx.HTTPError as exc:
            return {"url": url, "error": str(exc)}

        content_type = response.headers.get("content-type", "")
        text = response.text
        if max_chars > 0 and len(text) > max_chars:
            text = f"{text[:max_chars]}...(truncated)"

        result: dict[str, Any] = {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "headers": dict(response.headers),
            "text": text,
        }
        if "application/json" in content_type:
            with suppress(ValueError):
                result["json"] = response.json()
        if response.status_code >= 400:
            result["error"] = f"HTTP {response.status_code}"
        return result
