"""Instance-scoped credentials held exclusively in macOS Keychain.

Inputs: Provider API keys entered by the local user. Outputs: status metadata.
Assumptions: One trusted OS user; Keychain is not a sandbox against local malware.
No plaintext fallback, credential logging or secret export. Author: Carter Tan.
"""
import sys
from datetime import datetime, timezone
from uuid import uuid4

from src.storage import Store

PROVIDERS = ("openai", "anthropic", "openrouter")


class CredentialError(Exception):
    """Safe, fixed error text that never incorporates a credential."""


class Credentials:
    """Keep secrets in Keychain and non-secret references in instance storage."""

    def __init__(self, store: Store, backend=None) -> None:
        """Create an instance identity; an injected backend is for isolated tests."""
        self.store = store
        identity = store.get("instance", "identity")
        if identity is None:
            identity = store.put("instance", {"id": "identity", "uuid": str(uuid4())})
        self.service = "com.mybulter.enterprise." + identity["uuid"]
        self.backend = backend

    def _backend(self):
        """Select only the native macOS backend; never auto-select plaintext storage."""
        if self.backend is None:
            try:
                if sys.platform != "darwin":
                    raise RuntimeError("Unsupported platform")
                from keyring.backends.macOS import Keyring
                backend = Keyring()
                if backend.priority <= 0:
                    raise RuntimeError("Backend unavailable")
                backend.keychain = None
                self.backend = backend
            except Exception:
                raise CredentialError("macOS Keychain is unavailable. Install the application dependencies and use the local macOS session.") from None
        return self.backend

    def status(self, provider: str) -> dict:
        """Return saved metadata without reading a secret or prompting the OS."""
        self._validate_provider(provider)
        record = self.store.get("credential", provider) or {}
        return {"provider": provider, "configured": bool(record.get("configured")),
                "updated": record.get("updated"), "storage": "macOS Keychain",
                "verified": False}

    @staticmethod
    def _validate_provider(provider: str) -> None:
        """Restrict lookup and mutation to the supported provider accounts."""
        if provider not in PROVIDERS:
            raise CredentialError("Unsupported credential provider.")

    def save(self, provider: str, key: str) -> dict:
        """Store a key without returning, logging or persisting it in SQLite."""
        self._validate_provider(provider)
        prefixes = {"openai": "sk-", "anthropic": "sk-ant-api", "openrouter": "sk-or-"}
        if not isinstance(key, str) or not 20 <= len(key) <= 4096 or not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key):
            raise CredentialError("Enter a provider API key without spaces or line breaks.")
        if not key.startswith(prefixes[provider]) or key.startswith("sk-ant-oat"):
            raise CredentialError("Use an API key from the selected provider's console, not a Claude Code or Codex sign-in token.")
        if provider == "openai" and key.startswith(("sk-ant-", "sk-or-")):
            raise CredentialError("This key belongs to another provider. Select its provider instead.")
        try:
            self._backend().set_password(self.service, provider, key)
        except Exception:
            raise CredentialError("Keychain could not save the key. Unlock your login Keychain and allow access, then retry.") from None
        self.store.put("credential", {"id": provider, "configured": True,
                                      "updated": datetime.now(timezone.utc).isoformat()})
        return self.status(provider)

    def get(self, provider: str) -> str:
        """Read a configured secret for a single provider call; fail closed."""
        if not self.status(provider)["configured"]:
            raise CredentialError("Add this provider's API key in Models & connections first.")
        try:
            key = self._backend().get_password(self.service, provider)
        except Exception:
            raise CredentialError("Keychain access was denied or unavailable. Unlock it and retry.") from None
        if not key:
            raise CredentialError("The saved key is missing from Keychain. Add it again on this Mac.")
        return key

    def remove(self, provider: str) -> dict:
        """Disconnect only this instance's provider entry; never revoke remotely."""
        self._validate_provider(provider)
        if self.status(provider)["configured"]:
            try:
                backend = self._backend()
                if backend.get_password(self.service, provider) is not None:
                    backend.delete_password(self.service, provider)
            except Exception:
                raise CredentialError("Keychain could not remove the saved key. Unlock it and retry.") from None
        self.store.put("credential", {"id": provider, "configured": False,
                                      "updated": datetime.now(timezone.utc).isoformat()})
        return self.status(provider)
