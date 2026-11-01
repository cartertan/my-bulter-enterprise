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
from lxml import etree as ET

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from src.attachments import office_paragraphs


def compose_presentation(manifest: dict, sources: list[dict], template: bytes | None = None) -> bytes:
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

    def textbox(slide, x: float, y: float, width: float, height: float, text: str, size: int, color: str) -> None:
        """Add editable text with explicit typography and no automatic shrink."""
        box = slide.shapes.add_textbox(*bounds(x, y, width, height))
        box.text_frame.word_wrap = True
        box.text_frame.margin_left = box.text_frame.margin_right = Inches(.05)
        box.text_frame.text = text
        for paragraph in box.text_frame.paragraphs:
            paragraph.font.name = font_name
            paragraph.font.size = Pt(size * font_scale)
            paragraph.font.color.rgb = RGBColor.from_string(color)

    for index, item in enumerate(manifest['slides']):
        flow = item.get('flow_steps', [])
        if any(re.search(r'\{\{[^}]+\}\}', value) for value in [item['title'], item['body'], item['speaker_notes'], *flow]):
            raise ValueError('Resolve template placeholders before composing the presentation.')
        if len(item['title']) > 90 or len(item['body']) > (420 if flow else 700):
            raise ValueError('Slide text exceeds the standard layout budget. Shorten the title or body; nothing was omitted.')
        if flow and (not 2 <= len(flow) <= 5 or any(not value.strip() or len(value) > 50 for value in flow)):
            raise ValueError('A flow diagram needs two to five labels of at most 50 characters.')
        citations = sorted({entry['source_id'] for claim in item.get('claims', []) for entry in claim['evidence']})
        if len(citations) > 4 or any(identifier not in source_names for identifier in citations):
            raise ValueError('Slide citations must identify at most four registered sources.')
        slide = deck.slides.add_slide(layout)
        for placeholder in list(slide.placeholders):
            placeholder._element.getparent().remove(placeholder._element)
        header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *bounds(0, 0, 13.333, 1.25))
        header.fill.solid()
        header.fill.fore_color.rgb = RGBColor.from_string(navy)
        header.line.fill.background()
        textbox(slide, .65, .2, 12, .9, item['title'], 28, 'FFFFFF')
        textbox(slide, .7, 1.65, 5.4 if flow else 11.8, 4.5, item['body'], 22, ink)
        for position, label in enumerate(flow):
            y = 1.55 + position * .9
            node = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, *bounds(7, y, 5.4, .65))
            node.fill.solid()
            node.fill.fore_color.rgb = RGBColor.from_string(teal)
            node.line.fill.background()
            node.text_frame.text = label
            for paragraph in node.text_frame.paragraphs:
                paragraph.font.name = font_name
                paragraph.font.size = Pt(18 * font_scale)
                paragraph.font.color.rgb = RGBColor(255, 255, 255)
            if position + 1 < len(flow):
                arrow = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, *bounds(9.45, y + .67, .35, .2))
                arrow.fill.solid()
                arrow.fill.fore_color.rgb = RGBColor.from_string(teal)
                arrow.line.fill.background()
        citation_text = '\n'.join(source_names[identifier] for identifier in citations)
        if len(citation_text) > 320:
            raise ValueError('Citation labels exceed the slide footer budget; shorten source titles.')
        textbox(slide, .7, 6.15, 11.8, .8, citation_text, 10, ink)
        textbox(slide, .7, 7.05, 11.8, .3, f"{index + 1} / {len(manifest['slides'])}   |   {item['duration_seconds']} seconds   |   Draft — validation pending", 10, ink)
        provenance = '\n'.join(f"{citation['source_id']}: {citation['quote']}" for claim in item.get('claims', []) for citation in claim['evidence'])
        slide.notes_slide.notes_text_frame.text = (item['speaker_notes'] + f"\nSpeaking time: {item['duration_seconds']} seconds."
            + f"\nPresentation discussion: {manifest['discussion_seconds']} seconds (once, not per slide).\nSource evidence:\n" + provenance)
    output = io.BytesIO()
    deck.save(output)
    return output.getvalue()
