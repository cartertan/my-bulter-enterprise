"""Render a hash-verified application PPTX into local review evidence.

Inputs: Exported PPTX, expected artifact SHA-256, new private output directory.
Outputs: PDF, per-slide PNGs and a hash-bound JSON report; no acceptance verdict.
Assumptions: LibreOffice and pdftoppm are installed locally. No network or model
calls are made by this script. Review only trusted, validated Office packages.
Author: Carter Tan.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import unicodedata

import pdfplumber
from PIL import Image
from pptx import Presentation
import io

# Support the documented direct invocation from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.attachments import office_paragraphs

LOGGER = logging.getLogger(__name__)


def slide_text_fragments(shapes) -> list[str]:
    """Collect editable slide text, including groups/tables, excluding notes."""
    fragments = []
    for shape in shapes:
        if shape.has_text_frame:
            fragments.extend(p.text for p in shape.text_frame.paragraphs if p.text.strip())
        if shape.has_table:
            fragments.extend(cell.text for row in shape.table.rows for cell in row.cells if cell.text.strip())
        if shape.shape_type == 6:  # PowerPoint group; children have their own text frames.
            fragments.extend(slide_text_fragments(shape.shapes))
    return fragments


def text_presence(expected: list[str], rendered: str) -> dict:
    """Flag missing extracted text without claiming layout or semantic correctness."""
    def normalize(value: str) -> str:
        return ''.join(unicodedata.normalize('NFKC', value).split())
    actual = normalize(rendered)
    missing = [fragment for fragment in expected if normalize(fragment) not in actual]
    return {'state': 'needs_review' if missing else ('present' if expected else 'not_assessed'),
            'expected_fragments': len(expected), 'missing_fragments': missing}


def render_presentation(source: Path, expected_sha256: str, output: Path) -> dict:
    """Create fresh render evidence; reject stale hashes and incomplete page sets."""
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError('Input does not match the expected artifact SHA-256.')
    office_paragraphs(data, 'artifact.pptx')
    deck = Presentation(io.BytesIO(data))
    slide_count = len(deck.slides)
    if not slide_count:
        raise ValueError('The presentation has no slides.')
    renderer, rasterizer = shutil.which('soffice'), shutil.which('pdftoppm')
    if not renderer or not rasterizer:
        raise ValueError('Local LibreOffice (soffice) and pdftoppm are required.')
    # Never reuse prior evidence or overwrite a user's files, even on retry.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    output = output.resolve()
    local_source = output / 'artifact.pptx'
    local_source.write_bytes(data)
    profile = output / 'office-profile'
    subprocess.run([renderer, f'-env:UserInstallation={profile.as_uri()}', '--headless',
                    '--convert-to', 'pdf', '--outdir', str(output), str(local_source)],
                   check=True, capture_output=True, timeout=120)
    pdf = output / 'artifact.pdf'
    if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
        raise ValueError('Renderer did not produce a valid PDF.')
    with pdfplumber.open(pdf) as document:
        page_count = len(document.pages)
        extracted = [page.extract_text() or "" for page in document.pages]
    if page_count != slide_count:
        raise ValueError('Rendered page count does not match the source slide count.')
    subprocess.run([rasterizer, '-png', '-r', '120', str(pdf), str(output / 'slide')],
                   check=True, capture_output=True, timeout=120)
    pages = []
    for number in range(1, slide_count + 1):
        # Poppler pads page numbers to the total page count's digit width.
        path = output / f'slide-{number:0{len(str(slide_count))}d}.png'
        if not path.is_file() or not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('A rendered slide image is missing or invalid.')
        image_bytes = path.read_bytes()
        # A PNG signature alone also accepts truncated or corrupt raster output.
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.verify()
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.load()
                dimensions = list(image.size)
        except (OSError, SyntaxError) as exc:
            raise ValueError('A rendered slide image cannot be decoded.') from exc
        pages.append({'slide': number, 'file': path.name, 'sha256': hashlib.sha256(image_bytes).hexdigest(),
                      'dimensions': dimensions,
                      'text_presence': text_presence(slide_text_fragments(deck.slides[number - 1].shapes), extracted[number - 1])})
    report = {'artifact_sha256': digest, 'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
              'slide_count': slide_count, 'pages': pages, 'render_status': 'complete',
              'text_presence': 'needs_review' if any(page['text_presence']['state'] == 'needs_review' for page in pages) else 'no_missing_fragments_detected',
              'visual_inspection': 'pending', 'user_acceptance': 'not_assessed'}
    (output / 'render-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> int:
    """Render privately and log only outcome, never document text or command output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        report = render_presentation(args.source, args.sha256, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        LOGGER.error('Render evidence incomplete (%s); use a new output directory on retry.', type(exc).__name__)
        return 1
    LOGGER.info('Rendered %s slides. Visual inspection and acceptance remain pending.', report['slide_count'])
    if report['text_presence'] == 'needs_review':
        LOGGER.warning('Some slide text was not found in PDF extraction; inspect the private report.')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
