"""Run one offline MFLUX image job in the isolated image environment.

Inputs: Task and output directory arguments; prompt, size and seed via JSON stdin.
Outputs: PNG without prompt metadata and a private model verification receipt.
Assumptions: Invoked by local_visuals with offline/telemetry protections; model setup is separate.
Author: Carter Tan.
"""

import argparse
import fcntl
import json
import logging
import os
from pathlib import Path
import sys
import time

from src.image_engine import ENGINE_VERSION, MODELS, RUNTIME

LOGGER = logging.getLogger(__name__)


def run(task: str, destination: Path, request: dict) -> None:
    """Load only an allowlisted local snapshot and save an image without embedded prompts."""
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                       "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1"})
    from importlib.metadata import version
    if version("mflux") != ENGINE_VERSION:
        raise ValueError("Image engine version differs from the tested version.")
    prompt, size, seed = request["prompt"], request["size"], request["seed"]
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 6000 or size not in (512, 768, 1024) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("Invalid visual request.")
    if not destination.resolve().is_relative_to((RUNTIME / "visuals").resolve()):
        raise ValueError("Output must stay in the private visual directory.")
    model_path = RUNTIME / "image-models" / (task + "-4bit")
    # Offline environment plus explicit local paths prevent implicit model downloads.
    from mflux.models.common.config import ModelConfig
    if task == "flux":
        from mflux.models.flux2.variants import Flux2Klein
        model = Flux2Klein(model_config=ModelConfig.flux2_klein_4b(), model_path=str(model_path), quantize=4)
    else:
        from mflux.models.z_image import ZImageTurbo
        model = ZImageTurbo(model_path=str(model_path), quantize=4)
    started = time.monotonic()
    result = model.generate_image(prompt=prompt, seed=seed, width=size, height=size, num_inference_steps=MODELS[task]["steps"])
    # Saving fresh pixels avoids MFLUX's default prompt/EXIF metadata export.
    from PIL import Image
    clean = Image.new("RGB", result.image.size)
    clean.paste(result.image.convert("RGB"))
    with (destination / "image.png").open("xb") as output:
        clean.save(output, format="PNG")
    files = {str(p.relative_to(model_path)): p.stat().st_size for p in model_path.rglob("*")
             if p.is_file() and ".cache" not in p.parts and p.name != "verified.json"}
    receipt = {"engine": ENGINE_VERSION, "revision": MODELS[task]["revision"], "files": files,
               "model": MODELS[task]["label"], "quantization_bits": 4, "seed": seed,
               "size": size, "steps": MODELS[task]["steps"], "generation_seconds": round(time.monotonic()-started, 2)}
    (model_path / "verified.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    (destination / "generation.json").write_text(json.dumps({k: v for k, v in receipt.items() if k != "files"}, indent=2), encoding="utf-8")


def main() -> int:
    """Serialize GPU jobs and return sanitized failures to the parent process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=MODELS)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        with (RUNTIME / "image-engine.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run(args.task, args.destination, json.loads(sys.stdin.read(30000)))
        return 0
    except Exception as exc:
        # The engine can raise many backend-specific errors; never echo prompts or raw traces.
        LOGGER.error("Local image job failed (%s). Check setup, available memory and that no other image job is running.", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
