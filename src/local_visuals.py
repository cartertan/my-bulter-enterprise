"""Generate local diagrams or pictures using Ollama for diagrams and MFLUX for pictures.

Inputs: A task (diagram, flux, photo) and a UTF-8 prompt on standard input.
Outputs: A new private job folder with SVG or locally generated PNG files.
Assumptions: Ollama is running locally; models are installed; one visual job at a time.
No vault access, paid APIs, shell execution or generated-code execution.
Author: Carter Tan.
"""

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET

import httpx

LOGGER = logging.getLogger(__name__)
MODELS = {"diagram": "qwen3.8:27b", "flux": "x/flux2-klein:4b", "photo": "x/z-image-turbo:fp8"}
GRAPH_SCHEMA = {
    "type": "object", "required": ["nodes", "edges"], "additionalProperties": False,
    "properties": {
        "nodes": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
            "type": "object", "required": ["id", "label"], "additionalProperties": False,
            "properties": {"id": {"type": "string"}, "label": {"type": "string"}}}},
        "edges": {"type": "array", "maxItems": 20, "items": {
            "type": "object", "required": ["source", "target", "label"], "additionalProperties": False,
            "properties": {k: {"type": "string"} for k in ("source", "target", "label")}}},
    },
}


def render_graph(graph: dict) -> bytes:
    """Validate a small graph and render escaped text using fixed SVG elements only."""
    if not isinstance(graph, dict) or set(graph) != {"nodes", "edges"}:
        raise ValueError("Diagram must contain nodes and edges.")
    nodes, edges = graph["nodes"], graph["edges"]
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 12 or not isinstance(edges, list) or len(edges) > 20:
        raise ValueError("Diagram exceeds the supported graph size.")
    ids = set()
    for item in nodes + edges:
        if not isinstance(item, dict):
            raise ValueError("Diagram items must be objects.")
        expected = {"id", "label"} if item in nodes else {"source", "target", "label"}
        if set(item) != expected or any(not isinstance(v, str) or len(v) > 100 or any(ord(c) < 32 for c in v) for v in item.values()):
            raise ValueError("Diagram fields must be short plain text.")
    for node in nodes:
        if not node.get("id") or node["id"] in ids:
            raise ValueError("Diagram node IDs must be unique.")
        ids.add(node["id"])
    if any(edge.get("source") not in ids or edge.get("target") not in ids for edge in edges):
        raise ValueError("Diagram contains an unknown connection.")
    # Fixed vertical layout favors legibility and never interprets model text as markup.
    height = max(240, len(nodes) * 110 + 60, len(edges) * 48 + 90)
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", viewBox=f"0 0 1000 {height}", role="img")
    ET.SubElement(svg, "title").text = "Locally generated architecture draft; verify technical accuracy"
    ET.SubElement(svg, "rect", width="1000", height=str(height), fill="#191714")
    positions = {node["id"]: 40 + i * 110 for i, node in enumerate(nodes)}
    for i, edge in enumerate(edges):
        start, end = positions[edge["source"]] + 35, positions[edge["target"]] + 35
        bend = 400 + i * 6
        ET.SubElement(svg, "path", d=f"M 370 {start} H {bend} V {end} H 376", fill="none", stroke="#bfa782", **{"stroke-width": "2"})
        ET.SubElement(svg, "path", d=f"M 377 {end-5} L 370 {end} L 377 {end+5}", fill="none", stroke="#bfa782")
        # A separate connection list avoids overlapping labels on bidirectional edges.
        for line_index, line in enumerate(textwrap.wrap(f"{edge['source']} → {edge['target']}: {edge['label']}", width=48)[:2]):
            ET.SubElement(svg, "text", x="550", y=str(60+i*48+line_index*16), fill="#e7dcc7", **{"font-size": "13", "font-family": "sans-serif"}).text = line
    for node in nodes:
        y = positions[node["id"]]
        ET.SubElement(svg, "rect", x="30", y=str(y), width="340", height="70", rx="10", fill="#29251e", stroke="#bfa782")
        for i, line in enumerate(textwrap.wrap(f"{node['id']}: {node['label']}", width=32)[:3]):
            ET.SubElement(svg, "text", x="48", y=str(y+22+i*18), fill="#f2e9d8", **{"font-size": "16", "font-family": "sans-serif"}).text = line
    return ET.tostring(svg, encoding="utf-8", xml_declaration=True)


def generate_diagram(prompt: str, destination: Path) -> None:
    """Ask Qwen for structured graph data, then render without executing generated SVG."""
    with httpx.Client(timeout=600, trust_env=False) as client:
        response = client.post("http://127.0.0.1:11434/api/chat", json={
            "model": MODELS["diagram"], "stream": False, "think": False, "keep_alive": 0,
            "format": GRAPH_SCHEMA, "options": {"num_ctx": 8192, "num_predict": 2048},
            "messages": [{"role": "system", "content": "Return a concise directed architecture graph as JSON. At most 12 nodes and 20 edges. Use short plain-text labels. Do not invent facts; represent only the requested components."},
                         {"role": "user", "content": prompt}],
        })
        response.raise_for_status()
        graph = json.loads(response.json()["message"]["content"])
    svg = render_graph(graph)
    (destination / "diagram.svg").write_bytes(svg)
    (destination / "diagram.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")


def generate_picture(task: str, prompt: str, destination: Path, size: int = 768, seed: int = 42) -> None:
    """Run a fixed local MFLUX worker; keep prompts out of argv and disable network fallback."""
    from src.image_engine import RUNTIME, MODELS as IMAGE_MODELS
    if task not in IMAGE_MODELS:
        raise ValueError("Unknown image task.")
    executable = RUNTIME / "mflux-venv/bin/python"
    if not executable.is_file():
        raise ValueError("Run the image setup script first.")
    # Inherit only OS essentials; never propagate provider keys or Hugging Face tokens.
    env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR", "LANG") if key in os.environ}
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1", "TOKENIZERS_PARALLELISM": "false",
                "HF_HOME": str(RUNTIME / "hf-cache"), "XDG_CACHE_HOME": str(RUNTIME / "cache"),
                "MPLCONFIGDIR": str(RUNTIME / "cache/matplotlib")})
    result = subprocess.run([str(executable), "-m", "src.mflux_worker", task, str(destination.resolve())],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            input=json.dumps({"prompt": prompt, "size": size, "seed": seed}),
                            text=True, capture_output=True, timeout=900, check=False)
    if result.returncode or not (destination / "image.png").is_file():
        raise ValueError("Local image generation failed; check the image setup and available memory.")


def main() -> int:
    """Read a bounded prompt and save a fresh local visual job without overwriting files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=MODELS)
    parser.add_argument("--size", type=int, choices=(512, 768, 1024), default=768)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        prompt = sys.stdin.read(6001).strip()
        if not prompt or len(prompt) > 6000:
            raise ValueError("Supply a prompt of 1–6000 characters on standard input.")
        root = Path(__file__).resolve().parent / ".runtime" / "visuals"
        if any(p.is_symlink() for p in (root, root.parent)):
            raise ValueError("Visual output directories cannot be symlinks.")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix=args.task + "-", dir=root))
        if args.task == "diagram":
            generate_diagram(prompt, destination)
        else:
            generate_picture(args.task, prompt, destination, args.size, args.seed)
        LOGGER.info("Visual output saved in %s", destination)
        return 0
    except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError, subprocess.SubprocessError):
        LOGGER.error("Visual generation failed. Check the local engine, installed models and prompt size; no cloud fallback was used.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
