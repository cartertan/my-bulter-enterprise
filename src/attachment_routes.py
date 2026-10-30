"""Authenticated mission attachments, kept outside the shared memory vault.

Inputs: Uploaded bytes and selected attachment IDs. Outputs: local metadata and
normalized image previews. Assumption: Single-user instance. Author: Carter Tan.
"""
import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from src.documents import MAX_UPLOAD


def public_attachment(record: dict) -> dict:
    """Exclude binary source and image payloads from mission/state snapshots."""
    return {key: value for key, value in record.items() if key not in {"raw", "image"}}


async def require_vision(bots: list[dict]) -> None:
    """Fail closed unless every image recipient advertises local vision support."""
    for bot in bots:
        if bot["provider"] != "ollama":
            raise HTTPException(400, "Photo missions currently require only Ollama vision-capable Bulters.")
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                response = await client.post("http://127.0.0.1:11434/api/show", json={"model": bot["model"]})
                response.raise_for_status()
                if "vision" not in response.json().get("capabilities", []):
                    raise HTTPException(400, "A selected Ollama model does not support vision. Choose a vision model for every Bulter.")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise HTTPException(400, "Could not verify Ollama vision capability. Check that Ollama is running.") from exc


def install_attachment_routes(app, store) -> None:
    """Register upload/preview routes under the existing CSRF middleware."""
    lock = asyncio.Lock()

    @app.post("/api/attachments")
    async def upload(request: Request, filename: str) -> dict:
        """Parse uploads in a bounded worker and retain an immutable local source."""
        if not filename or len(filename) > 150 or any(c in filename for c in '/\\\x00\r\n'):
            raise HTTPException(400, "Use a plain filename of up to 150 characters.")
        raw = await request.body()
        if not raw or len(raw) > MAX_UPLOAD:
            raise HTTPException(400, "Choose a nonempty file up to 10 MB.")
        async with lock:
            if len(store.all("attachment")) >= 200:
                raise HTTPException(400, "This instance has reached its 200-attachment storage limit.")
            try:
                result = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "src.attachments", filename],
                                                input=raw, capture_output=True, timeout=30,
                                                cwd=Path(__file__).resolve().parents[1])
                parsed = json.loads(result.stdout)
                if result.returncode or "error" in parsed:
                    raise ValueError(parsed.get("error", "Attachment parser failed."))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
                raise HTTPException(400, "Attachment could not be parsed within its resource limits.") from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            record = {"id": str(uuid4()), "filename": filename, "size": len(raw), **parsed,
                      "raw": base64.b64encode(raw).decode()}
            store.put("attachment", record)
            return public_attachment(record)

    @app.get("/api/attachments/{identifier}/preview")
    async def preview(identifier: str) -> Response:
        """Return only a normalized still image, never an executable uploaded file."""
        record = store.get("attachment", identifier)
        if not record or record["kind"] != "image":
            raise HTTPException(404, "Photo not found.")
        return Response(base64.b64decode(record["image"]), media_type="image/jpeg")
