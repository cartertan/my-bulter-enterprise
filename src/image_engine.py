"""Local image engine configuration and lightweight readiness checks.

Inputs: Private model installation and smoke-test receipts. Outputs: public status only.
Assumptions: Single trusted macOS user; paths are derived from this source tree.
Author: Carter Tan.
"""

import json
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent / ".runtime"
ENGINE_VERSION = "0.23.0"
MODELS = {
    "flux": {"label": "FLUX.2 Klein 4B", "repo": "mlx-community/flux2-klein-4b-4bit", "revision": "860e87183ceb29e39627c0612ebd66d8ea66e68c", "steps": 4},
    "photo": {"label": "Z-Image Turbo", "repo": "filipstrand/Z-Image-Turbo-mflux-4bit", "revision": "b3a8f31115a11f2f9e2fa0bfbc8d78dcc3e6568b", "steps": 9},
}


def engine_status(root: Path = RUNTIME) -> dict:
    """Report tested readiness without loading a GPU model or making network calls."""
    installed = (root / "mflux-venv/bin/python").is_file()
    models = {}
    for task, spec in MODELS.items():
        status = "Engine not installed" if not installed else "Setup or verification needed"
        directory = root / "image-models" / (task + "-4bit")
        try:
            receipt = json.loads((directory / "verified.json").read_text())
            files = receipt["files"]
            safe_files = isinstance(files, dict) and bool(files) and all(
                isinstance(name, str) and not Path(name).is_absolute() and ".." not in Path(name).parts
                and (directory / name).is_file() and not (directory / name).is_symlink()
                and (directory / name).stat().st_size == size for name, size in files.items())
            if installed and safe_files and receipt["engine"] == ENGINE_VERSION and receipt["revision"] == spec["revision"]:
                status = "Ready · local generation tested"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        models[task] = {"label": spec["label"], "status": status}
    return {"engine": "MFLUX", "version": ENGINE_VERSION, "models": models}
