"""Mission attachment parsing and source-preserving Office template output.

Inputs: Bounded uploaded bytes and completed mission output. Outputs: safe previews
and editable Office bytes. Assumptions: Files are untrusted, never executable;
Office templates use explicit {{RESPONSE}} placeholders. Author: Carter Tan.
"""
import base64
import io
import json
import ipaddress
import re
import sys
import warnings
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from lxml import etree as ET

from PIL import Image, ImageOps
from src.documents import MAX_UPLOAD, extract_text

IMAGE_TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
MAX_REFERENCE = 12000


def citation_target_allowed(target: str) -> bool:
    """Accept bounded HTTPS citation syntax without resolving or fetching URLs.

    Only DNS names and default HTTPS ports are allowed. This validates syntax,
    not the publisher's trustworthiness, DNS resolution or citation accuracy.
    """
    if (not target or len(target) > 2048 or "\\" in target
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in target)
            or re.search(r"%(?![0-9a-fA-F]{2})", target)
            or any(ord(char) < 32 or ord(char) == 127 for char in unquote(target))):
        return False
    try:
        url = urlsplit(target)
        host = url.hostname or ""
        if (url.scheme != "https" or url.username is not None or url.password is not None
                or url.port not in (None, 443) or not host or host.endswith(".")):
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return False
        # Reject intranet names and malformed authorities; no DNS lookup occurs.
        labels = host.split(".")
        return (len(host) <= 253 and len(labels) >= 2
                and labels[-1] not in {"localhost", "local", "internal", "invalid", "test"}
                and not labels[-1].isdigit()
                and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                        for label in labels))
    except ValueError:
        return False


def validate_office_part(name: str, content: bytes) -> None:
    """Reject active package parts and allow only validated external hyperlinks."""
    lowered = name.lower()
    if "/embeddings/" in lowered or "/activex/" in lowered:
        raise ValueError("Remove embedded objects or active content from this Office file.")
    if not lowered.endswith(".rels"):
        return
    namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    hyperlink_types = {"http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                       "http://purl.oclc.org/ooxml/officeDocument/relationships/hyperlink"}
    try:
        root = ET.fromstring(content, parser=ET.XMLParser(resolve_entities=False, no_network=True))
        if root.tag != f"{{{namespace}}}Relationships" or root.getroottree().docinfo.doctype:
            raise ValueError("Invalid Office relationships.")
        identifiers = set()
        for node in root:
            identifier, target = node.get("Id"), node.get("Target", "")
            if (node.tag != f"{{{namespace}}}Relationship" or not identifier or identifier in identifiers
                    or not target or not node.get("Type")):
                raise ValueError("Invalid Office relationships.")
            identifiers.add(identifier)
            mode = node.get("TargetMode", "Internal")
            if mode == "External":
                if node.get("Type") not in hyperlink_types or not citation_target_allowed(target):
                    raise ValueError("Only validated HTTPS citation hyperlinks may be external Office relationships.")
            elif mode != "Internal" or "\\" in target or urlsplit(target).scheme or target.startswith("//"):
                raise ValueError("Invalid internal Office relationship target or mode.")
    except ET.XMLSyntaxError as exc:
        raise ValueError("Invalid Office relationships XML.") from exc


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
            validate_office_part(item.filename, content)
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


def office_paragraphs(data: bytes, filename: str, *, include_notes: bool = False) -> list[str]:
    """Extract editable text, optionally including speaker bodies for artifact review."""
    extract_text(data, filename)
    paragraphs = []
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        for name in source.namelist():
            validate_office_part(name, source.read(name))
            if name == "word/document.xml" or (name.startswith("ppt/slides/slide") and name.endswith(".xml")):
                root = ET.fromstring(source.read(name), parser=ET.XMLParser(resolve_entities=False, no_network=True))
                ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main" if name.startswith("word/") else "http://schemas.openxmlformats.org/drawingml/2006/main"
                for paragraph in root.iter(f"{{{ns}}}p"):
                    text = "".join(node.text or "" for node in paragraph.iter(f"{{{ns}}}t"))
                    if text.strip():
                        paragraphs.append(text)
            elif include_notes and name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml"):
                root = ET.fromstring(source.read(name), parser=ET.XMLParser(resolve_entities=False, no_network=True))
                namespaces = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                              "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                for shape in root.findall(".//p:sp", namespaces):
                    # Only speaker bodies are substantive; skip slide numbers and master furniture.
                    if shape.find("p:nvSpPr/p:nvPr/p:ph[@type='body']", namespaces) is None:
                        continue
                    for paragraph in shape.findall(".//a:p", namespaces):
                        text = "".join(node.text or "" for node in paragraph.findall(".//a:t", namespaces))
                        if text.strip():
                            paragraphs.append("Speaker notes: " + text)
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
            validate_office_part(item.filename, content)
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
