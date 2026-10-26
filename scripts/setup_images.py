"""Install the isolated MFLUX environment and download pinned public model snapshots.

Inputs: Explicit invocation; optional --download-only for an existing image environment.
Outputs: Private engine environment and resumable model downloads under src/.runtime.
Assumptions: macOS Apple Silicon, Python 3.11+, internet access and approximately 15 GB free disk.
Author: Carter Tan.
"""

import argparse
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.image_engine import MODELS, RUNTIME

LOGGER = logging.getLogger(__name__)
PATTERNS = ["vae/*.safetensors", "vae/*.json", "transformer/*.safetensors", "transformer/*.json",
            "text_encoder/*.safetensors", "text_encoder/*.json", "tokenizer/**", "added_tokens.json", "chat_template.jinja"]


def main() -> int:
    """Install optional image dependencies without changing the application environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise ValueError("This image setup requires Apple Silicon macOS.")
        engine = RUNTIME / "mflux-venv"
        if RUNTIME.is_symlink() or engine.is_symlink() or (RUNTIME / "image-models").is_symlink():
            raise ValueError("Runtime directories must not be symlinks.")
        env = {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR", "LANG") if k in os.environ}
        env.update({"HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1", "HF_HUB_DISABLE_XET": "1",
                    "HF_HOME": str(RUNTIME / "hf-cache")})
        if not args.download_only:
            if not (engine / "bin/python").is_file():
                venv.EnvBuilder(with_pip=True).create(engine)
            subprocess.run([str(engine / "bin/python"), "-m", "pip", "install", "-r", str(ROOT / "src/image-requirements.txt")],
                           env=env, check=True, timeout=1200)
            subprocess.run([str(engine / "bin/python"), str(Path(__file__).resolve()), "--download-only"],
                           env=env, check=True, timeout=14400)
        else:
            from huggingface_hub import snapshot_download
            for task, spec in MODELS.items():
                LOGGER.info("Downloading pinned %s snapshot; interrupted downloads resume.", spec["label"])
                snapshot_download(spec["repo"], revision=spec["revision"], token=False, allow_patterns=PATTERNS,
                                  local_dir=RUNTIME / "image-models" / (task + "-4bit"), max_workers=3)
            LOGGER.info("Models downloaded. Run one flux and photo job to verify local inference.")
        return 0
    except Exception as exc:
        LOGGER.error("Image setup failed (%s). Check platform, free disk and network access; existing files were retained.", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
