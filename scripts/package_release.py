"""Validate and package an explicit source allowlist for GitHub distribution.

Inputs: Repository source files; optional --check flag.
Outputs: Validation log, or a new source ZIP with an SHA-256 manifest.
Assumptions: Run from any directory; root is this script's parent directory.
No network, Git mutations, credential reads or existing-file overwrites.
Author: Carter Tan.
"""

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "scripts/check_release.py", "src/tests/test_mission_reliability.py", "src/docs/REMEDIATION_PLAN.md",
    "src/docs/learning/README.md", "src/docs/learning/BUTLER_CASE_STUDY.md",
    "src/docs/learning/WORKFLOW_TEMPLATES.md",
    "src/attachments.py", "src/attachment_routes.py", "src/static/attachments.js",
    "src/tests/test_attachments.py", "src/docs/MISSION_ATTACHMENTS.md", "src/docs/screenshots/mission-attachments.jpg",
    "src/docs/UPLOAD_2026-10-27.md", "src/docs/screenshots/connectors-connected.jpg",
    "src/connectors.py", "src/connector_routes.py", "src/static/connectors.js",
    "src/tests/test_connectors.py", "src/docs/CONNECTORS.md", "scripts/run_browser_mcp.sh",
    ".gitignore", "src/local_visuals.py", "src/image_engine.py", "src/mflux_worker.py", "scripts/setup_images.py", "src/image-requirements.txt", "src/tests/test_local_visuals.py", "src/docs/LOCAL_VISUALS.md", "src/docs/screenshots/model-concierge.jpg", "src/docs/screenshots/image-engine-ready.jpg", "src/docs/screenshots/flux-example.jpg", "src/docs/screenshots/photo-example.jpg", "README.md", "scripts/run.sh", "scripts/package_release.py",
    "src/.gitignore", "src/__init__.py", "src/app.py", "src/providers.py", "src/storage.py",
    "src/documents.py", "src/tests/test_documents.py", "src/docs/DOCUMENT_WORKFLOW.md", "src/docs/screenshots/document-memory.jpg",
    "src/docs/UPLOAD_2026-10-26.md",
    "src/credentials.py", "src/tests/test_credentials.py", "src/docs/CREDENTIALS_AND_VISUALS.md",
    "src/requirements.txt", "src/README.md", "src/static/index.html", "src/static/style.css",
    "src/static/app.js", "src/tests/test_app.py", "src/tests/test_package.py",
    "src/docs/SETUP.md", "src/docs/ARCHITECTURE.md", "src/docs/BUILD_ACTIVITY.md",
    "src/docs/SECURITY.md", "src/docs/PUBLISHING.md",
    "src/obsidian.py", "scripts/init_vault.py", "src/tests/test_obsidian.py", "src/tests/test_retrieval.py",
    "src/docs/OBSIDIAN.md", "src/docs/MEMORY_EXPORT_PROMPT.md", "src/docs/MEMORY_NOTE_TEMPLATE.md",
    "src/tests/test_scenarios.py", "src/docs/CHECKPOINT_2026-10-23.md",
    "src/docs/GALLERY.md", "src/docs/screenshots/dashboard.jpg", "src/docs/screenshots/missions.jpg",
    "src/docs/screenshots/memory.jpg", "src/docs/screenshots/models.jpg",
)
PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"/Users/[A-Za-z0-9_.-]+/"),
)


def validate_text(name: str, data: bytes) -> None:
    """Reject obvious credentials or workstation paths without echoing values."""
    text = data.decode("utf-8")
    if any(pattern.search(text) for pattern in PATTERNS):
        raise ValueError(f"Review required: suspicious credential or personal path pattern in {name}")


def validate_candidates(candidates: list[str]) -> None:
    """Refuse unreviewed Git candidates, including already-tracked local data."""
    unexpected = sorted(set(candidates) - set(FILES))
    if unexpected:
        # Report count only: arbitrary filenames can themselves contain private data.
        raise ValueError(f"Git contains {len(unexpected)} file(s) outside the reviewed allowlist. Inspect git status before publishing.")


def collect(root: Path) -> dict[str, bytes]:
    """Read only explicit paths; reject missing files and symlink escapes."""
    payload = {}
    for name in FILES:
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Path escapes repository: {name}")
        # Check each ancestor explicitly, even if a symlink still resolves within root.
        current = path
        while current != root:
            if current.is_symlink():
                raise ValueError(f"Symlink not allowed: {name}")
            current = current.parent
        data = path.read_bytes()
        if name.endswith((".jpg", ".png")):
            # Only explicitly allowlisted, reviewed demo screenshots are packaged.
            signature = b"\x89PNG\r\n\x1a\n" if name.endswith(".png") else b"\xff\xd8\xff"
            if not data.startswith(signature) or len(data) > 10_000_000:
                raise ValueError(f"Invalid or oversized screenshot: {name}")
        else:
            validate_text(name, data)
        payload[name] = data
    if (root / ".git").exists():
        result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                cwd=root, capture_output=True, check=True, timeout=15)
        validate_candidates([p for p in result.stdout.decode("utf-8").split("\0") if p])
    return payload


def create_archive(root: Path, payload: dict[str, bytes]) -> Path:
    """Write a new ZIP with a manifest; never include discovered runtime files."""
    destination = root / "src" / ".release"
    if destination.is_symlink():
        raise ValueError("Release directory must not be a symlink.")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = destination / f"my-bulter-enterprise-source-{stamp}.zip"
    manifest = {"format_version": 1, "files": {
        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in payload.items()
    }}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in payload.items():
            bundle.writestr(f"my-bulter-enterprise/{name}", data)
        bundle.writestr("my-bulter-enterprise/SOURCE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Archive integrity verification failed.")
    return archive


def main() -> int:
    """Run read-only preflight or build a new reviewed source archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate only; do not create an archive")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        payload = collect(ROOT)
        LOGGER.info("Validated %d allowlisted source files; no selected credential/path patterns found.", len(payload))
        if not args.check:
            LOGGER.info("Created source archive: %s", create_archive(ROOT, payload))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        LOGGER.error("Packaging stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
