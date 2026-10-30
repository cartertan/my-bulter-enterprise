"""Mission attachment parsing and source-preserving Office template output.

Inputs: Bounded uploaded bytes and completed mission output. Outputs: safe previews
and editable Office bytes. Assumptions: Files are untrusted, never executable;
Office templates use explicit {{RESPONSE}} placeholders. Author: Carter Tan.
"""
import base64
import io
import json
import sys
import warnings
import zipfile
from pathlib import Path
from lxml import etree as ET

from PIL import Image, ImageOps
from src.documents import MAX_UPLOAD, extract_text

IMAGE_TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
MAX_REFERENCE = 12000


def parse(data: bytes, filename: str) -> dict:
    """Decode actual content; strip image metadata and bound decoded dimensions."""
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("Choose a nonempty file up to 10 MB.")
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_TYPES:
        Image.MAX_IMAGE_PIXELS = 20_000_000
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != IMAGE_TYPES[suffix] or source.width * source.height > 20_000_000:
                    raise ValueError("Image format mismatch or image exceeds 20 megapixels.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Upload a single still image.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1600, 1600))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
                return {"kind": "image", "text": "", "image": base64.b64encode(output.getvalue()).decode(),
                        "width": image.width, "height": image.height}
    text = extract_text(data, filename)
    if len(text) > MAX_REFERENCE:
        raise ValueError("Extracted text exceeds 12,000 characters. Split the document into smaller files; nothing was truncated.")
    return {"kind": "document", "text": text}


def template_output(data: bytes, filename: str, mission: dict) -> bytes:
    """Replace explicit markers, including split runs, while retaining Office parts."""
    if mission.get("status") != "completed":
        raise ValueError("Complete the mission before exporting a template.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".docx", ".pptx"}:
        raise ValueError("Templates must be DOCX or PPTX files.")
    extract_text(data, filename)  # Repeat ZIP and macro limits before opening the package.
    replacements = {"{{RESPONSE}}": mission["steps"][-1]["output"], "{{REQUEST}}": mission["prompt"]}
    output = io.BytesIO()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
        for item in source.infolist():
            content = source.read(item.filename)
            # External links/embedded files are not copied into a generated deliverable.
            if "/embeddings/" in item.filename or "/activeX/" in item.filename:
                raise ValueError("Templates with embedded objects or active content are not supported.")
            if item.filename.endswith(".rels"):
                root = ET.fromstring(content, parser=ET.XMLParser(resolve_entities=False, no_network=True))
                if any(node.attrib.get("TargetMode") == "External" for node in root):
                    raise ValueError("Remove external links from the template before exporting.")
            eligible = item.filename == "word/document.xml" or (item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml"))
            if eligible:
                root = ET.fromstring(content, parser=ET.XMLParser(resolve_entities=False, no_network=True))
                ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main" if suffix == ".docx" else "http://schemas.openxmlformats.org/drawingml/2006/main"
                for paragraph in root.iter(f"{{{ns}}}p"):
                    nodes = list(paragraph.iter(f"{{{ns}}}t"))
                    text = "".join(node.text or "" for node in nodes)
                    if "{{RESPONSE}}" in text:
                        count += 1
                    if not any(key in text for key in replacements):
                        continue
                    for key, value in replacements.items():
                        text = text.replace(key, value)
                    if nodes:
                        nodes[0].text = text
                        nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        for node in nodes[1:]:
                            node.text = ""
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            destination.writestr(item, content)
    if not count:
        raise ValueError("Add {{RESPONSE}} to a paragraph or slide text box in the template first.")
    return output.getvalue()


def main() -> None:
    """Run parsing in a time-limited worker; never return parser exception details."""
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    try:
        result = parse(sys.stdin.buffer.read(MAX_UPLOAD + 1), sys.argv[1])
    except ValueError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "Cannot decode this file. Upload a valid supported document or still photo."}
    sys.stdout.write(json.dumps(result))


def office_paragraphs(data: bytes, filename: str) -> list[str]:
    """Expose exact editable paragraph text for grounded replacement proposals."""
    extract_text(data, filename)
    paragraphs = []
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        for name in source.namelist():
            if name == "word/document.xml" or (name.startswith("ppt/slides/slide") and name.endswith(".xml")):
                root = ET.fromstring(source.read(name), parser=ET.XMLParser(resolve_entities=False, no_network=True))
                ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main" if name.startswith("word/") else "http://schemas.openxmlformats.org/drawingml/2006/main"
                for paragraph in root.iter(f"{{{ns}}}p"):
                    text = "".join(node.text or "" for node in paragraph.iter(f"{{{ns}}}t"))
                    if text.strip():
                        paragraphs.append(text)
    return paragraphs


def edited_output(data: bytes, filename: str, mission: dict) -> bytes:
    """Apply validated exact-text edits to a new package; never invent edit targets."""
    if mission.get("status") != "completed":
        raise ValueError("Complete the mission before exporting edits.")
    raw = mission["steps"][-1]["output"].strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[7:-3].strip()
    try:
        payload = json.loads(raw)
        edits = payload["replacements"]
        if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
            raise ValueError
        paragraphs = office_paragraphs(data, filename)
        replacements = {}
        for edit in edits:
            old, new = edit["old"], edit["new"]
            if not isinstance(old, str) or not isinstance(new, str) or not old or len(new) > 12000 or old in replacements or paragraphs.count(old) != 1:
                raise ValueError
            replacements[old] = new
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("The proposed edits are invalid or ambiguous. Ask for JSON replacements targeting unique, exact source paragraphs.") from exc
    # Reuse the package security checks before constructing the replacement copy.
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
        for item in source.infolist():
            content = source.read(item.filename)
            if "/embeddings/" in item.filename or "/activeX/" in item.filename:
                raise ValueError("Remove embedded objects or active content from this Office file.")
            if item.filename.endswith(".rels"):
                root = ET.fromstring(content, parser=ET.XMLParser(resolve_entities=False, no_network=True))
                if any(node.attrib.get("TargetMode") == "External" for node in root):
                    raise ValueError("Remove external links from the Office file before exporting.")
            if item.filename == "word/document.xml" or (item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml")):
                root = ET.fromstring(content, parser=ET.XMLParser(resolve_entities=False, no_network=True))
                ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main" if item.filename.startswith("word/") else "http://schemas.openxmlformats.org/drawingml/2006/main"
                for paragraph in root.iter(f"{{{ns}}}p"):
                    nodes = list(paragraph.iter(f"{{{ns}}}t"))
                    old = "".join(node.text or "" for node in nodes)
                    if old in replacements:
                        nodes[0].text = replacements[old]
                        nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        for node in nodes[1:]:
                            node.text = ""
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            destination.writestr(item, content)
    return output.getvalue()


if __name__ == "__main__":
    main()
