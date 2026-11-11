"""Compose editable PowerPoint drafts from validated timed slide manifests.

Inputs: Validated TimedPresentation dictionaries and selected source metadata.
Outputs: In-memory PPTX bytes; no filesystem or network side effects.
Assumptions: Fixed composition grid; optional template theme/master/dimensions.
Source sample slides are replaced, not reproduced. Layout fidelity needs rendering.
Reject oversized content rather than silently dropping or shrinking it.
Author: Carter Tan.
"""
import io
import re
import hashlib
from PIL import Image
from lxml import etree as ET

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Inches, Pt
from pptx.shapes.autoshape import Shape
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from src.attachments import office_paragraphs, citation_target_allowed


TITLE_LIMIT = 90
BODY_LIMIT = 700
PANEL_BODY_LIMIT = 420
FLOW_LABEL_LIMIT = 50


def compose_presentation(manifest: dict, sources: list[dict], template: bytes | None = None,
                         images: dict[str, dict] | None = None) -> bytes:
    """Build real editable text, flow shapes, timing and provenance speaker notes."""
    if template:
        office_paragraphs(template, 'template.pptx')  # Validate package safety before reuse.
    deck = Presentation(io.BytesIO(template)) if template else Presentation()
    if not template:
        deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    ratio = deck.slide_width / deck.slide_height
    if not 1.3 <= ratio <= 2 or not Inches(8) <= deck.slide_width <= Inches(20):
        raise ValueError('Composition supports landscape templates with aspect ratio 1.3–2 and width 8–20 inches.')
    x_scale, y_scale = deck.slide_width / Inches(13.333), deck.slide_height / Inches(7.5)
    font_scale = min(x_scale, y_scale)
    layout = min(deck.slide_layouts, key=lambda item: len(item.placeholders))
    # Remove sample slides only in the new in-memory package; masters/layouts remain.
    if template:
        for identifier in list(deck.slides._sldIdLst):
            deck.part.drop_rel(identifier.rId)
            deck.slides._sldIdLst.remove(identifier)
    navy, teal, ink = '142D40', '087F8C', '203647'
    font_name = 'Aptos'
    if template:
        theme = ET.fromstring(deck.slide_master.part.part_related_by(RT.THEME).blob,
                             parser=ET.XMLParser(resolve_entities=False, no_network=True))
        ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
        for role, fallback in (('dk2', navy), ('accent1', teal), ('dk1', ink)):
            nodes = theme.xpath(f'./a:themeElements/a:clrScheme/a:{role}/*', namespaces=ns)
            value = (nodes[0].get('lastClr') or nodes[0].get('val')) if nodes else fallback
            value = value if value and re.fullmatch('[0-9A-Fa-f]{6}', value) else fallback
            if role == 'dk2': navy = value
            elif role == 'accent1': teal = value
            else: ink = value
        fonts = theme.xpath('./a:themeElements/a:fontScheme/a:minorFont/a:latin/@typeface', namespaces=ns)
        if fonts and fonts[0]: font_name = fonts[0]

    def bounds(x: float, y: float, width: float, height: float) -> tuple:
        """Scale the composition grid to the retained template dimensions."""
        return Inches(x * x_scale), Inches(y * y_scale), Inches(width * x_scale), Inches(height * y_scale)
    source_names = {source['source_id']: f"S{index + 1}: {source['title']}" for index, source in enumerate(sources)}
    source_metadata = {source['source_id']: source for source in sources}
    images = images or {}

    def configure_text(shape, text: str, size: int, color: str) -> None:
        """Reject explicit line overflow; wrapping still requires rendered validation."""
        frame = shape.text_frame
        frame.word_wrap = True
        frame.auto_size = MSO_AUTO_SIZE.NONE
        frame.margin_left = frame.margin_right = Inches(.05 * x_scale)
        frame.margin_top = frame.margin_bottom = Inches(.05 * y_scale)
        font_points = size * font_scale
        usable_points = (shape.height - frame.margin_top - frame.margin_bottom) / 12700
        # Character limits alone permit many short lines that cannot fit vertically.
        # CRLF is one break; PowerPoint also treats vertical tabs as soft breaks.
        lines = len(re.split(r"\r\n|[\n\r\v]", text))
        if lines * font_points * 1.2 > usable_points:
            raise ValueError('Explicit text lines exceed the slide panel height; shorten or split the content.')
        frame.text = text.replace('\r\n', '\n').replace('\r', '\n')
        for paragraph in frame.paragraphs:
            paragraph.space_before = paragraph.space_after = Pt(0)
            # Percentage spacing depends on font metrics and exceeded the reserved panel in renders.
            paragraph.line_spacing = Pt(font_points * 1.2)
            paragraph.font.name = font_name
            paragraph.font.size = Pt(font_points)
            paragraph.font.color.rgb = RGBColor.from_string(color)

    def textbox(slide, x: float, y: float, width: float, height: float, text: str, size: int, color: str) -> Shape:
        """Add editable text with explicit typography and no automatic shrink."""
        box = slide.shapes.add_textbox(*bounds(x, y, width, height))
        configure_text(box, text, size, color)
        return box

    for index, item in enumerate(manifest['slides']):
        flow = item.get('flow_steps', [])
        image_id = item.get('image_id')
        caption = item.get('image_caption', '')
        if image_id and (image_id not in images or flow or not caption.strip() or len(caption) > 120):
            raise ValueError('Picture slides require a selected image, a caption up to 120 characters and no flow diagram on the same slide.')
        if any(re.search(r'\{\{[^}]+\}\}', value) for value in [item['title'], item['body'], item['speaker_notes'], caption, *flow]):
            raise ValueError('Resolve template placeholders before composing the presentation.')
        if any(re.search(r'\$[^$]*\\[A-Za-z]+[^$]*\$|\\\(|\\\[', value)
               for value in [item['title'], item['body'], item['speaker_notes'], caption, *flow]):
            raise ValueError('LaTeX math is not rendered. Use plain text or Unicode symbols and flow_steps for diagrams; no text was rewritten.')
        if len(item['title']) > TITLE_LIMIT or len(item['body']) > (PANEL_BODY_LIMIT if flow or image_id else BODY_LIMIT):
            raise ValueError('Slide text exceeds the standard layout budget. Shorten the title or body; nothing was omitted.')
        if flow and (not 2 <= len(flow) <= 5 or any(not value.strip() or len(value) > FLOW_LABEL_LIMIT for value in flow)):
            raise ValueError('A flow diagram needs two to five labels of at most 50 characters.')
        citations = sorted({entry['source_id'] for claim in item.get('claims', []) for entry in claim['evidence']})
        if len(citations) > 4 or any(identifier not in source_names for identifier in citations):
            raise ValueError('Slide citations must identify at most four registered sources.')
        for identifier in citations:
            url = source_metadata[identifier].get('source_url')
            if url and (not isinstance(url, str) or not citation_target_allowed(url)):
                raise ValueError('A cited source URL does not satisfy the HTTPS citation policy.')
        slide = deck.slides.add_slide(layout)
        for placeholder in list(slide.placeholders):
            placeholder._element.getparent().remove(placeholder._element)
        header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *bounds(0, 0, 13.333, 1.25))
        header.fill.solid()
        header.fill.fore_color.rgb = RGBColor.from_string(navy)
        header.line.fill.background()
        textbox(slide, .65, .2, 12, .9, item['title'], 28, 'FFFFFF')
        textbox(slide, .7, 1.65, 5.4 if flow or image_id else 11.8, 4.1, item['body'], 20 if flow or image_id else 22, ink)
        image_note = ''
        if image_id:
            asset = images[image_id]
            with Image.open(io.BytesIO(asset['bytes'])) as photo:
                width, height = photo.size
                if photo.format != 'JPEG' or width * height > 20_000_000:
                    raise ValueError('Composition requires normalized JPEG attachments within image limits.')
            left, top, box_width, box_height = bounds(7, 1.55, 5.4, 3.5)
            scale = min(box_width / width, box_height / height)
            drawn_width, drawn_height = int(width * scale), int(height * scale)
            slide.shapes.add_picture(io.BytesIO(asset['bytes']), left + (box_width - drawn_width) // 2,
                                    top + (box_height - drawn_height) // 2, drawn_width, drawn_height)
            textbox(slide, 7, 5.15, 5.4, .65, caption, 14, ink)
            image_note = (f"\nImage attachment: {image_id} | {asset['filename']}"
                          f"\nNormalized image SHA-256: {hashlib.sha256(asset['bytes']).hexdigest()}"
                          '\nImage origin: user-selected upload; rights and factual interpretation not verified.')
        for position, label in enumerate(flow):
            y = 1.55 + position * .9
            node = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, *bounds(7, y, 5.4, .65))
            node.fill.solid()
            node.fill.fore_color.rgb = RGBColor.from_string(teal)
            node.line.fill.background()
            configure_text(node, label, 18, 'FFFFFF')
            if position + 1 < len(flow):
                arrow = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, *bounds(9.45, y + .67, .35, .2))
                arrow.fill.solid()
                arrow.fill.fore_color.rgb = RGBColor.from_string(teal)
                arrow.line.fill.background()
        # Reserve the bottom half-inch of the grid for retained master/footer branding.
        citation_text = '\n'.join(source_names[identifier] for identifier in citations)
        if len(citation_text) > 320:
            raise ValueError('Citation labels exceed the slide footer budget; shorten source titles.')
        citation_box = textbox(slide, .7, 5.85, 11.8, .8, citation_text, 10, ink)
        paragraph_index = 0
        for identifier in citations:
            label = source_names[identifier].replace('\r\n', '\n').replace('\r', '\n')
            count = len(label.split('\n'))
            url = source_metadata[identifier].get('source_url')
            if url:
                for paragraph in citation_box.text_frame.paragraphs[paragraph_index:paragraph_index + count]:
                    for run in paragraph.runs:
                        run.hyperlink.address = url
            paragraph_index += count
        textbox(slide, .7, 6.7, 11.8, .3, f"{index + 1} / {len(manifest['slides'])}   |   {item['duration_seconds']} seconds   |   Draft — validation pending", 10, ink)
        provenance = '\n'.join(f"{citation['source_id']}: {citation['quote']}" for claim in item.get('claims', []) for citation in claim['evidence'])
        metadata_notes = []
        for identifier in citations:
            source = source_metadata[identifier]
            metadata_notes.append(f"{source_names[identifier]} | Source ID: {identifier}"
                + f"\nSource URL: {source.get('source_url') or 'not supplied'}"
                + f"\nRecorded at (not retrieval/publication date): {source.get('recorded_at') or 'not recorded'}"
                + f"\nRetrieved at: {source.get('retrieved_at') or 'not verified'}"
                + f"\nSource scope: {source.get('scope') or 'not specified'}"
                + f"\nProvenance: {source.get('provenance') or 'unverified'}")
        # Put full metadata in notes, avoiding URL overflow in the visible citation panel.
        provenance += '\nSource metadata:\n' + '\n'.join(metadata_notes)
        slide.notes_slide.notes_text_frame.text = (item['speaker_notes'] + f"\nSpeaking time: {item['duration_seconds']} seconds."
            + f"\nPresentation discussion: {manifest['discussion_seconds']} seconds (once, not per slide).\nSource evidence:\n" + provenance + image_note)
    output = io.BytesIO()
    deck.save(output)
    return output.getvalue()
