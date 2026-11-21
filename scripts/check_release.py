"""Run the local source-release gates without publishing.

Inputs: Repository sources and the current installed Python/Node environment.
Outputs: Check logs and a nonzero exit code on any failure.
Assumptions: Run from a trusted checkout; dependencies already installed. No
network, staging, commits, deletion or publication. Author: Carter Tan.
"""
import logging
from pathlib import Path
import shutil
import subprocess
import sys

LOGGER = logging.getLogger(__name__)


def main() -> int:
    """Execute tests, JavaScript parsing and source-only packaging preflight."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    if not node:
        LOGGER.error("Node.js is required for the release JavaScript syntax gate.")
        return 1
    checks = [("Python regression suite", [sys.executable, "-m", "pytest", "src/tests", "-q", "-p", "no:cacheprovider"])]
    checks.extend((f"JavaScript syntax: {path.name}", [node, "--check", str(path)])
                  for path in sorted((root / "src" / "static").glob("*.js")))
    checks.append(("Source-only package preflight", [sys.executable, "scripts/package_release.py", "--check"]))
    try:
        for label, command in checks:
            LOGGER.info("Running %s", label)
            subprocess.run(command, cwd=root, check=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.error("Release checks failed (%s). Nothing was published.", type(exc).__name__)
        return 1
    LOGGER.info("Local release checks passed. Human source review and end-to-end acceptance remain required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
