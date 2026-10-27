"""Local-user connector routes with explicit preview/confirmation boundaries.

Inputs: CSRF-protected dashboard requests and state-bound Google callback.
Outputs: Status, reference snapshots and auditable action results.
Assumptions: Installed only behind app.local_guard. Author: Carter Tan.
"""
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from src.connectors import Connectors, ConnectorError, text_field


async def body(request: Request, fields: set[str]) -> dict:
    """Validate secret-bearing input without FastAPI echoing rejected values."""
    try:
        data = await request.json()
        if not isinstance(data, dict) or set(data) - fields:
            raise ValueError("Invalid fields")
        return data
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Provide the expected connector form fields.") from None


def install_connector_routes(app: FastAPI, connectors: Connectors) -> None:
    """Install only fixed operations; no arbitrary HTTP or tool-execution endpoint."""
    @app.exception_handler(ConnectorError)
    async def connector_error(request: Request, exc: ConnectorError):
        """Return only deliberately sanitized connector messages."""
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/connectors")
    async def status() -> dict:
        """Read metadata without Keychain/network access."""
        return {"connections": connectors.status(),
                "evidence": connectors.store.all("connector_evidence")[::-1][:50],
                "actions": connectors.store.all("connector_action")[::-1][:50]}

    @app.post("/api/connectors/google/connect")
    async def google_connect(request: Request) -> dict:
        """Begin user-driven OAuth with a loopback callback."""
        data = await body(request, {"client_id", "client_secret"})
        port = request.url.port or 80
        async with connectors.lock:
            return await connectors.google_start(data, f"http://127.0.0.1:{port}/oauth/google/callback")

    @app.get("/oauth/google/callback", response_class=HTMLResponse)
    async def google_callback(request: Request) -> HTMLResponse:
        """Cross-site GET is allowed only here, secured by expiring state and PKCE."""
        try:
            async with connectors.lock:
                await connectors.google_callback(request.query_params.get("state", ""), request.query_params.get("code", ""))
            message = "Google connected. Close this tab and refresh Connectors in My Bulter Enterprise."
        except ConnectorError:
            message = "Google authorization did not complete. Return to My Bulter Enterprise and reconnect."
        # Never reflect authorization codes, provider errors or request URLs.
        return HTMLResponse("<!doctype html><title>Google connection</title><p>" + message + "</p><a href='/'>Return to dashboard</a>")

    @app.post("/api/connectors/google/read")
    async def google_read(request: Request) -> dict:
        """Fetch explicit reference data; nothing is sent to an LLM automatically."""
        data = await body(request, {"kind", "query"})
        kind = text_field(data, "kind", 20)
        query = text_field(data, "query", 500, False) or "is:unread"
        async with connectors.lock:
            return await connectors.google_read(kind, query)

    @app.post("/api/connectors/telegram/connect")
    async def telegram_connect(request: Request) -> dict:
        """Keep the token write-only and pair a private chat before use."""
        data = await body(request, {"token"})
        async with connectors.lock:
            return await connectors.telegram_start(text_field(data, "token", 200))

    @app.post("/api/connectors/telegram/pair")
    async def telegram_pair() -> dict:
        """Check the short-lived pairing challenge on explicit user request."""
        async with connectors.lock:
            return await connectors.telegram_pair()

    @app.post("/api/connectors/telegram/inbox")
    async def telegram_inbox() -> list[dict]:
        """Import paired-user text into a review queue, not an autonomous task queue."""
        async with connectors.lock:
            return await connectors.telegram_inbox()

    @app.post("/api/connectors/browser/capture")
    async def browser_capture() -> dict:
        """Capture the page the user opened in a separate local browser MCP."""
        async with connectors.lock:
            return await connectors.browser_snapshot()

    @app.post("/api/connectors/manual")
    async def manual(request: Request) -> dict:
        """Record only the excerpt the user explicitly pasted for analysis."""
        data = await body(request, {"text"})
        return connectors.evidence("manual", "User-provided excerpt", text_field(data, "text", 6000))

    @app.post("/api/connectors/actions/prepare")
    async def prepare(request: Request) -> dict:
        """Save a preview; creating a preview never invokes an external write."""
        data = await body(request, {"kind", "to", "subject", "body", "summary", "description", "start", "end", "event_id", "text"})
        async with connectors.lock:
            return await connectors.prepare(text_field(data, "kind", 40), data)

    @app.post("/api/connectors/actions/{identifier}/confirm")
    async def confirm(identifier: str, request: Request) -> dict:
        """Confirm exactly the server-stored preview, never replacement arguments."""
        data = await body(request, {"confirm"})
        if data.get("confirm") is not True:
            raise ConnectorError("Review the preview and explicitly confirm this action.")
        async with connectors.lock:
            return await connectors.confirm(identifier)

    @app.post("/api/connectors/actions/{identifier}/cancel")
    async def cancel(identifier: str) -> dict:
        """Cancel a pending local preview without affecting external data."""
        async with connectors.lock:
            action = connectors.store.get("connector_action", identifier)
            if not action or action["status"] != "pending":
                raise ConnectorError("Only pending previews can be cancelled.")
            return connectors.store.put("connector_action", {**action, "status": "cancelled"})

    @app.post("/api/connectors/{name}/disconnect")
    async def disconnect(name: str) -> dict:
        """Explicitly remove this instance's local connector entry only."""
        async with connectors.lock:
            await connectors.disconnect(name)
        return {"disconnected": True}
