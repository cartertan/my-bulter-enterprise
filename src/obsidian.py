"""Read approved Obsidian notes without writing back to the vault.

Inputs: Explicit vault directory and user-reviewed Markdown with YAML properties.
Outputs: Scoped memory records and source hashes; no network calls.
Assumptions: One trusted local user; raw exports are never prompt context.
Author: Carter Tan.
"""

import hashlib
import os
import re
from pathlib import Path

import yaml

from src.storage import Store

DEFAULT_VAULT = Path(__file__).resolve().parent / ".runtime" / "My Bulter Memory"
FOLDERS = ("10 Profile", "20 Preferences", "30 Workflows", "40 Projects", "50 Shared Knowledge", "60 Bulters")


def read_notes(vault: Path, owners: set[str]) -> list[dict]:
    """Validate every eligible note before returning approved memory records."""
    if not vault.is_dir() or vault.is_symlink():
        raise ValueError("Vault is missing or is a symbolic link. Open the configured local vault first.")
    notes, identifiers = [], set()
    count = 0
    for folder in FOLDERS:
        directory = vault / folder
        if directory.is_symlink():
            raise ValueError("Linked folders are not allowed in the memory import.")
        if not directory.exists():
            continue
        for parent, dirs, files in os.walk(directory, followlinks=False):
            if any((Path(parent) / name).is_symlink() for name in dirs):
                raise ValueError("Linked folders are not allowed in the memory import.")
            for name in sorted(files):
                path = Path(parent) / name
                if path.suffix.lower() != ".md":
                    continue
                count += 1
                if count > 500 or path.is_symlink() or path.stat().st_size > 16000:
                    raise ValueError("Import limit exceeded or linked note found (500 notes, 16 KB per file).")
                text = path.read_text(encoding="utf-8")
                match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)\Z", text, re.S)
                if not match:
                    raise ValueError(f"Missing note properties: {path.relative_to(vault)}")
                try:
                    props = yaml.safe_load(match[1])
                except yaml.YAMLError as exc:
                    raise ValueError(f"Invalid note properties: {path.relative_to(vault)}") from exc
                if not isinstance(props, dict) or props.get("status") not in ("draft", "approved", "archived"):
                    raise ValueError("Every managed note needs status: draft, approved or archived.")
                if props["status"] != "approved":
                    continue
                identifier = props.get("id")
                title, content = props.get("title"), match[2].strip()
                if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identifier):
                    raise ValueError("Approved notes need a stable id using letters, digits, hyphens or underscores.")
                if identifier in identifiers:
                    raise ValueError("Duplicate approved note ID. Resolve duplicates before syncing.")
                identifiers.add(identifier)
                if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or not 1 <= len(content) <= 3000:
                    raise ValueError("Approved notes need a title (1–100 characters) and body (1–3,000 characters).")
                if props.get("scope") not in ("shared", "private") or type(props.get("cloud_allowed")) is not bool:
                    raise ValueError("Approved notes need explicit scope and a boolean cloud_allowed property.")
                owner = props.get("owner_id") if props["scope"] == "private" else None
                if props["scope"] == "private" and (not isinstance(owner, str) or owner not in owners):
                    raise ValueError("Private notes need an existing Bulter ID in owner_id.")
                source = props.get("source", "user")
                if not isinstance(source, str) or len(source) > 200:
                    raise ValueError("Note source must be short text.")
                notes.append({"id": "obsidian-" + identifier, "title": title.strip(), "content": content,
                              "owner_id": owner, "cloud_allowed": props["cloud_allowed"], "active": True,
                              "source_type": "obsidian", "source": source,
                              "source_path": str(path.relative_to(vault)),
                              "source_hash": hashlib.sha256(text.encode()).hexdigest()})
    return notes


def sync_notes(store: Store, vault: Path) -> dict:
    """Atomically refresh approved notes and deactivate removed/revoked entries."""
    old = [m for m in store.all("memory") if m.get("source_type") == "obsidian"]
    if not vault.exists() and not old:
        return {"approved": 0, "deactivated": 0}
    notes = read_notes(vault, {b["id"] for b in store.all("bulter")})
    current = {m["id"] for m in notes}
    revoked = [{**m, "active": False} for m in old if m["id"] not in current]
    store.put_many("memory", notes + revoked)
    return {"approved": len(notes), "deactivated": sum(m["active"] for m in old if m["id"] not in current)}
