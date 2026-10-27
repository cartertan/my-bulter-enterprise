"""Explicit Gmail, Calendar, Telegram and browser-MCP connector operations.

Inputs: User-authorized requests and instance-scoped Keychain secrets.
Outputs: Bounded local evidence and confirmed external actions.
Assumptions: Single loopback app process; no autonomous model tool execution.
Secrets never enter SQLite, logs, model context or Obsidian. Author: Carter Tan.
"""
import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode, quote
from uuid import uuid4

import httpx

from src.credentials import Credentials, CredentialError
from src.storage import Store

GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events.owned",
)
MCP_URL = "http://127.0.0.1:8931/mcp"
LOGGER = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Fixed safe messages only; never include remote responses or URLs with secrets."""


def timestamp() -> str:
    """Return a timezone-aware evidence timestamp."""
    return datetime.now(timezone.utc).isoformat()


def text_field(data: dict, key: str, limit: int, required: bool = True) -> str:
    """Validate bounded text without echoing submitted values."""
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ConnectorError("Check the required fields and text lengths.")
    return value.strip()


class Connectors:
    """Keep network authority outside the model and serialize secret/write operations."""

    def __init__(self, store: Store, credentials: Credentials, transport=None) -> None:
        """Inject HTTP transport for offline security tests."""
        self.store, self.credentials, self.transport = store, credentials, transport
        self.lock = asyncio.Lock()
        self.oauth: dict = {}
        self.pairing: dict = {}
        self.mcp_headers: dict | None = None
        # Telegram embeds its token in the API path; HTTP request logging must be off.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        for action in store.all("connector_action"):
            if action["status"] == "sending":
                store.put("connector_action", {**action, "status": "unknown", "error": "Interrupted: inspect the external service before retrying."})

    def status(self) -> dict:
        """Expose metadata only, without causing Keychain access prompts."""
        return {name: self.store.get("connector", name) or {"id": name, "configured": False}
                for name in ("google", "telegram")}

    def _save_secret(self, name: str, value: dict) -> None:
        """Write only this instance's connector entry, with no plaintext fallback."""
        try:
            self.credentials._backend().set_password(self.credentials.service, "connector:" + name, json.dumps(value))
        except Exception:
            raise ConnectorError("Keychain could not save connector credentials. Unlock it and retry.") from None

    def _secret(self, name: str) -> dict:
        """Read a single connector credential without returning it to the dashboard."""
        try:
            value = self.credentials._backend().get_password(self.credentials.service, "connector:" + name)
            if not value:
                raise ValueError("Missing")
            return json.loads(value)
        except Exception:
            raise ConnectorError("Connector credentials are missing or Keychain access was denied. Connect again.") from None

    async def request(self, method: str, url: str, **kwargs) -> dict:
        """Make one bounded request; never retry writes with uncertain outcomes."""
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False,
                                        transport=self.transport) as client:
                async with client.stream(method, url, **kwargs) as response:
                    if not 200 <= response.status_code < 300:
                        raise ConnectorError("The service rejected the request. Check authorization, permissions or rate limits; inspect the service before retrying a write.")
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 2_000_000:
                            raise ConnectorError("The service response exceeded the safe size limit.")
                    if not body:
                        return {}
                    result = json.loads(body)
                    if not isinstance(result, dict):
                        raise ValueError("Object expected")
                    return result
        except ConnectorError:
            raise
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise ConnectorError("The service could not be reached or returned an invalid response. Inspect the service before retrying a write.") from None

    def evidence(self, source: str, title: str, content: str) -> dict:
        """Save bounded untrusted reference material locally, never automatic memory."""
        record = {"id": str(uuid4()), "source": source, "title": title, "created": timestamp(),
                  "content": content[:6000], "truncated": len(content) > 6000, "local_only": True}
        return self.store.put("connector_evidence", record)

    async def google_start(self, data: dict, redirect: str) -> dict:
        """Create an expiring, single-use OAuth state and S256 PKCE challenge."""
        client_id = text_field(data, "client_id", 300)
        client_secret = text_field(data, "client_secret", 500)
        if not client_id.endswith(".apps.googleusercontent.com") or any(c.isspace() for c in client_id):
            raise ConnectorError("Use a Google Desktop app OAuth client ID.")
        verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.oauth = {"state": state, "verifier": verifier, "expires": time.monotonic() + 600,
                      "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect}
        params = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code",
                  "scope": " ".join(GOOGLE_SCOPES), "state": state, "code_challenge": challenge,
                  "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
        return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}

    async def google_callback(self, state: str, code: str) -> None:
        """Consume state before exchange; refuse replay, expiry and partial permissions."""
        pending = self.oauth
        if not pending or pending["expires"] < time.monotonic() or not secrets.compare_digest(state.encode(), pending["state"].encode()):
            raise ConnectorError("Authorization expired or did not match. Start Connect Google again.")
        self.oauth = {}
        if not code or len(code) > 4096:
            raise ConnectorError("Google authorization was not completed. Start again when ready.")
        result = await self.request("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": pending["client_id"], "client_secret": pending["client_secret"],
            "redirect_uri": pending["redirect_uri"], "code": code,
            "code_verifier": pending["verifier"], "grant_type": "authorization_code"})
        if not set(GOOGLE_SCOPES).issubset(set(result.get("scope", "").split())) or not result.get("refresh_token"):
            raise ConnectorError("The requested Google permissions or offline grant were not supplied. Reconnect and review every requested permission.")
        value = {k: pending[k] for k in ("client_id", "client_secret")}
        value.update(refresh_token=result["refresh_token"])
        await asyncio.to_thread(self._save_secret, "google", value)
        self.store.put("connector", {"id": "google", "configured": True, "scopes": list(GOOGLE_SCOPES),
                                     "generation": str(uuid4()), "updated": timestamp()})

    async def google_token(self) -> str:
        """Refresh on demand; access tokens remain only in request memory."""
        value = await asyncio.to_thread(self._secret, "google")
        result = await self.request("POST", "https://oauth2.googleapis.com/token", data={**value, "grant_type": "refresh_token"})
        token = result.get("access_token")
        if not isinstance(token, str) or not token:
            raise ConnectorError("Google did not return an access token. Reconnect Google.")
        return token

    async def google_read(self, kind: str, query: str = "is:unread") -> dict:
        """Read bounded Gmail snippets or the next seven days of primary-calendar events."""
        auth = {"Authorization": "Bearer " + await self.google_token()}
        if kind == "gmail":
            result = await self.request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                        headers=auth, params={"q": query, "maxResults": 10})
            items = []
            for message in result.get("messages", [])[:10]:
                mid = quote(str(message["id"]), safe="")
                item = await self.request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/" + mid,
                                          headers=auth, params={"format": "metadata"})
                headers = {h["name"].lower(): h["value"] for h in item.get("payload", {}).get("headers", [])
                           if h.get("name", "").lower() in ("from", "to", "subject", "date")}
                items.append({"id": message["id"], **headers, "snippet": item.get("snippet", "")})
            return self.evidence("gmail", "Gmail search — first 10 results", json.dumps({"query": query, "messages": items}, ensure_ascii=False))
        if kind != "calendar":
            raise ConnectorError("Unsupported Google read operation.")
        start = datetime.now(timezone.utc)
        result = await self.request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events", headers=auth,
                                    params={"timeMin": start.isoformat(), "timeMax": (start + timedelta(days=7)).isoformat(),
                                            "singleEvents": "true", "orderBy": "startTime", "maxResults": 30})
        items = [{k: e.get(k) for k in ("id", "summary", "description", "start", "end", "location", "status")}
                 for e in result.get("items", [])[:30]]
        return self.evidence("calendar", "Primary calendar — next seven days (up to 30 events)", json.dumps(items, ensure_ascii=False))

    async def telegram(self, method: str, payload: dict, token: str | None = None) -> dict:
        """Call only fixed Bot API methods; secrets in Telegram's required URL never log."""
        if method not in ("getMe", "getUpdates", "sendMessage", "getWebhookInfo"):
            raise ConnectorError("Unsupported Telegram operation.")
        if token is None:
            token = (await asyncio.to_thread(self._secret, "telegram"))["token"]
        result = await self.request("POST", "https://api.telegram.org/bot" + token + "/" + method, json=payload)
        if result.get("ok") is not True:
            raise ConnectorError("Telegram rejected the operation. Check the bot and its permissions.")
        return result

    async def telegram_start(self, token: str) -> dict:
        """Validate a dedicated bot and issue a short-lived private-chat pairing code."""
        if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{25,100}", token):
            raise ConnectorError("Enter a valid BotFather token in the password field.")
        me = (await self.telegram("getMe", {}, token))["result"]
        webhook = (await self.telegram("getWebhookInfo", {}, token))["result"]
        if webhook.get("url"):
            raise ConnectorError("This bot already uses a webhook. Use a new dedicated bot; existing integrations will not be removed.")
        # Do not replace the live connection until the private pairing challenge succeeds.
        self.pairing = {"token": token, "code": secrets.token_urlsafe(18), "expires": time.monotonic() + 600,
                        "username": me.get("username", ""), "offset": 0}
        return {"command": "/start " + self.pairing["code"], "username": self.pairing["username"]}

    async def telegram_pair(self) -> dict:
        """Pair only a private human sender who supplied the one-time challenge."""
        pending = self.pairing
        if not pending or pending["expires"] < time.monotonic():
            self.pairing = {}
            raise ConnectorError("Pairing expired. Save the bot token again.")
        updates = (await self.telegram("getUpdates", {"offset": pending["offset"], "limit": 100, "timeout": 0,
                                                       "allowed_updates": ["message"]}, pending["token"]))["result"]
        for update in updates:
            pending["offset"] = max(pending["offset"], update["update_id"] + 1)
            message = update.get("message", {})
            sender, chat = message.get("from", {}), message.get("chat", {})
            text = message.get("text")
            if (chat.get("type") == "private" and not sender.get("is_bot") and sender.get("id") == chat.get("id")
                    and isinstance(text, str) and secrets.compare_digest(text.encode(), ("/start " + pending["code"]).encode())):
                await asyncio.to_thread(self._save_secret, "telegram", {"token": pending["token"]})
                record = {"id": "telegram", "configured": True, "chat_id": str(chat["id"]),
                          "user_id": str(sender["id"]), "username": pending["username"],
                          "offset": pending["offset"], "updated": timestamp()}
                self.store.put("connector", record)
                self.pairing = {}
                return {"paired": True}
        return {"paired": False, "message": "Send the displayed pairing command in your bot's private chat, then check again."}

    async def telegram_inbox(self) -> list[dict]:
        """Import text from the paired user only; never execute it or auto-reply."""
        connection = self.status()["telegram"]
        if not connection.get("configured"):
            raise ConnectorError("Pair your Telegram bot first.")
        updates = (await self.telegram("getUpdates", {"offset": connection["offset"], "limit": 100, "timeout": 0,
                                                     "allowed_updates": ["message"]}))["result"]
        evidence = []
        for update in updates:
            connection["offset"] = max(connection["offset"], update["update_id"] + 1)
            message = update.get("message", {})
            if (str(message.get("chat", {}).get("id")) == connection["chat_id"]
                    and message.get("chat", {}).get("type") == "private"
                    and str(message.get("from", {}).get("id")) == connection["user_id"]
                    and isinstance(message.get("text"), str)):
                # Persist deduplication with the evidence in one transaction before advancing offset.
                identifier = "telegram:" + connection["username"] + ":" + str(update["update_id"])
                if not self.store.get("connector_evidence", identifier):
                    item = {"id": identifier, "source": "telegram", "title": "Telegram message for review",
                            "created": timestamp(), "content": message["text"][:6000], "local_only": True}
                    self.store.put("connector_evidence", item)
                    evidence.append(item)
        self.store.put("connector", connection)
        return evidence

    async def prepare(self, kind: str, data: dict) -> dict:
        """Freeze exact outgoing content for local-user confirmation; never send here."""
        if kind == "gmail.send":
            payload = {key: text_field(data, key, limit) for key, limit in (("to", 254), ("subject", 200), ("body", 10000))}
            if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", payload["to"]) or any(c in payload["subject"] for c in "\r\n"):
                raise ConnectorError("Provide one email address and a single-line subject.")
        elif kind in ("calendar.create", "calendar.update", "calendar.delete"):
            payload = {}
            if kind != "calendar.create":
                event_id = text_field(data, "event_id", 1024)
                if not re.fullmatch(r"[A-Za-z0-9_-]+", event_id):
                    raise ConnectorError("Use an event ID from the primary calendar result.")
                payload["event_id"] = event_id
            if kind != "calendar.delete":
                payload.update({k: text_field(data, k, n, k != "description") for k, n in (("summary", 200), ("description", 4000), ("start", 40), ("end", 40))})
                try:
                    start, end = (datetime.fromisoformat(payload[k].replace("Z", "+00:00")) for k in ("start", "end"))
                    if start.utcoffset() is None or end.utcoffset() is None or start >= end:
                        raise ValueError("Invalid interval")
                except ValueError:
                    raise ConnectorError("Use start/end dates with a timezone offset and an end after the start.") from None
        elif kind == "telegram.send":
            connection = self.status()["telegram"]
            if not connection.get("configured"):
                raise ConnectorError("Pair Telegram first.")
            payload = {"text": text_field(data, "text", 4000), "chat_id": connection["chat_id"]}
        else:
            raise ConnectorError("Unsupported action.")
        if kind != "telegram.send" and not self.status()["google"].get("configured"):
            raise ConnectorError("Connect Google before preparing an action.")
        current_event = None
        if kind in ("calendar.update", "calendar.delete"):
            auth = {"Authorization": "Bearer " + await self.google_token()}
            event = await self.request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events/" + quote(payload["event_id"], safe=""), headers=auth)
            if not event.get("etag"):
                raise ConnectorError("The calendar event has no revision tag. Reload it before changing it.")
            current_event = {k: event.get(k) for k in ("id", "summary", "start", "end", "recurrence", "recurringEventId", "etag")}
            current_event["attendee_count"] = len(event.get("attendees", []))
        return self.store.put("connector_action", {"id": str(uuid4()), "kind": kind, "payload": payload,
                              "current_event": current_event,
                              "google_generation": self.status()["google"].get("generation") if kind != "telegram.send" else None,
                              "status": "pending", "created": timestamp(), "expires": time.time() + 900})

    async def confirm(self, identifier: str) -> dict:
        """Send a frozen, unexpired action once. Call only while holding self.lock."""
        action = self.store.get("connector_action", identifier)
        if not action or action["status"] != "pending" or action["expires"] < time.time():
            raise ConnectorError("This action expired or was already attempted. Review the service before creating another.")
        kind, payload = action["kind"], action["payload"]
        # Lock out a duplicate before any network I/O; ambiguous failures are not retried.
        action["status"] = "sending"
        self.store.put("connector_action", action)
        try:
            if kind == "telegram.send":
                current = self.status()["telegram"]
                if not current.get("configured") or current.get("chat_id") != payload["chat_id"]:
                    raise ConnectorError("Telegram recipient changed. Prepare a new preview.")
                result = (await self.telegram("sendMessage", {**payload, "link_preview_options": {"is_disabled": True}}))["result"]
                remote_id = str(result.get("message_id", ""))
            else:
                current = self.status()["google"]
                if not current.get("configured") or current.get("generation") != action.get("google_generation"):
                    raise ConnectorError("Google connection changed. Prepare a new preview for the current account.")
                auth = {"Authorization": "Bearer " + await self.google_token()}
                if action.get("current_event"):
                    auth["If-Match"] = action["current_event"]["etag"]
                if kind == "gmail.send":
                    message = EmailMessage()
                    message["To"], message["Subject"] = payload["to"], payload["subject"]
                    message.set_content(payload["body"])
                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    result = await self.request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers=auth, json={"raw": raw})
                else:
                    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
                    if "event_id" in payload:
                        url += "/" + quote(payload["event_id"], safe="")
                    if kind == "calendar.delete":
                        result = await self.request("DELETE", url, headers=auth, params={"sendUpdates": "all"})
                    else:
                        event = {"summary": payload["summary"], "description": payload["description"],
                                 "start": {"dateTime": payload["start"]}, "end": {"dateTime": payload["end"]}}
                        result = await self.request("POST" if kind == "calendar.create" else "PATCH", url,
                                                    headers=auth, params={"sendUpdates": "all"}, json=event)
                remote_id = str(result.get("id", ""))
            action.update(status="sent", remote_id=remote_id, finished=timestamp())
        except ConnectorError as exc:
            action.update(status="unknown", error=str(exc), finished=timestamp())
        return self.store.put("connector_action", action)

    async def notify_mission(self, mission: dict) -> None:
        """Send only an explicitly requested fixed status notice, never prompts or results."""
        connection = self.status()["telegram"]
        if not connection.get("configured") or connection.get("chat_id") != mission.get("telegram_chat_id"):
            raise ConnectorError("Telegram was disconnected or the recipient changed; notice not sent.")
        text = "My Bulter Enterprise: mission " + mission["id"] + " is " + mission["status"] + ". Review results on your Mac."
        await self.telegram("sendMessage", {"chat_id": connection["chat_id"], "text": text, "link_preview_options": {"is_disabled": True}})

    async def disconnect(self, name: str) -> None:
        """Remove only the named local connector secret; remote revocation is separate."""
        if name not in ("google", "telegram"):
            raise ConnectorError("Unknown connector.")
        try:
            backend = await asyncio.to_thread(self.credentials._backend)
            if await asyncio.to_thread(backend.get_password, self.credentials.service, "connector:" + name):
                await asyncio.to_thread(backend.delete_password, self.credentials.service, "connector:" + name)
        except Exception:
            raise ConnectorError("Keychain could not disconnect this connector.") from None
        self.oauth = {} if name == "google" else self.oauth
        self.pairing = {} if name == "telegram" else self.pairing
        self.store.put("connector", {"id": name, "configured": False, "updated": timestamp()})

    async def browser_snapshot(self) -> dict:
        """Use Streamable HTTP MCP for a single read-only snapshot; no arbitrary tools."""
        # Playwright normalizes its advertised loopback host to localhost. Keep the
        # TCP destination pinned to 127.0.0.1 while sending that canonical Host.
        headers = self.mcp_headers or {"Host": "localhost:8931", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                async def rpc(payload: dict) -> dict:
                    """Read JSON or bounded SSE until the matching JSON-RPC response."""
                    async with client.stream("POST", MCP_URL, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        if response.headers.get("mcp-session-id"):
                            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
                        if "id" not in payload:
                            return {}
                        if "text/event-stream" in response.headers.get("content-type", ""):
                            count = 0
                            async for line in response.aiter_lines():
                                count += len(line)
                                if count > 200_000:
                                    raise ConnectorError("Browser snapshot exceeded the size limit.")
                                if line.startswith("data:"):
                                    item = json.loads(line[5:])
                                    if item.get("id") == payload["id"]:
                                        return item
                        else:
                            body = bytearray()
                            async for part in response.aiter_bytes():
                                body.extend(part)
                                if len(body) > 200_000:
                                    raise ConnectorError("Browser snapshot exceeded the size limit.")
                            return json.loads(body)
                    raise ConnectorError("MCP did not return a matching response.")

                if self.mcp_headers is None:
                    initialized = await rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "My Bulter Enterprise", "version": "1"}}})
                    version = initialized.get("result", {}).get("protocolVersion")
                    if version not in ("2025-03-26", "2025-06-18", "2025-11-25"):
                        raise ConnectorError("Unsupported MCP protocol version.")
                    headers["MCP-Protocol-Version"] = version
                    await rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
                    self.mcp_headers = headers
                response = await rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                      "params": {"name": "browser_snapshot", "arguments": {}}})
                result = response.get("result", {})
                if response.get("error") or result.get("isError"):
                    raise ConnectorError("Browser capture failed. Open a page in the dedicated Playwright browser first.")
                content = "\n".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text")
                if not content.strip():
                    raise ConnectorError("No readable browser snapshot was returned.")
                return self.evidence("browser", "User-requested browser snapshot", content)
        except ConnectorError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self.mcp_headers = None
            raise ConnectorError("Browser MCP is unavailable. Start the dedicated Playwright MCP server on 127.0.0.1:8931.") from None
