"""Compose editable PowerPoint drafts from validated timed slide manifests.

Inputs: Validated TimedPresentation dictionaries and selected source metadata.
Outputs: In-memory PPTX bytes; no filesystem or network side effects.
Assumptions: Standard 16:9 layout, not a reproduction of an uploaded template.
Reject oversized content rather than silently dropping or shrinking it.
Author: Carter Tan.
"""
import io
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt


def compose_presentation(manifest: dict, sources: list[dict]) -> bytes:
    """Build real editable text, flow shapes, timing and provenance speaker notes."""
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    navy, teal, ink = '142D40', '087F8C', '203647'
    source_names = {source['source_id']: f"S{index + 1}: {source['title']}" for index, source in enumerate(sources)}

    def textbox(slide, x: float, y: float, width: float, height: float, text: str, size: int, color: str) -> None:
        """Add editable text with explicit typography and no automatic shrink."""
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height))
        box.text_frame.word_wrap = True
        box.text_frame.margin_left = box.text_frame.margin_right = Inches(.05)
        box.text_frame.text = text
        for paragraph in box.text_frame.paragraphs:
            paragraph.font.name = 'Aptos'
            paragraph.font.size = Pt(size)
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
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, deck.slide_width, Inches(1.25))
        header.fill.solid()
        header.fill.fore_color.rgb = RGBColor.from_string(navy)
        header.line.fill.background()
        textbox(slide, .65, .2, 12, .9, item['title'], 28, 'FFFFFF')
        textbox(slide, .7, 1.65, 5.4 if flow else 11.8, 4.5, item['body'], 22, ink)
        for position, label in enumerate(flow):
            y = 1.55 + position * .9
            node = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(7), Inches(y), Inches(5.4), Inches(.65))
            node.fill.solid()
            node.fill.fore_color.rgb = RGBColor.from_string(teal)
            node.line.fill.background()
            node.text_frame.text = label
            for paragraph in node.text_frame.paragraphs:
                paragraph.font.name = 'Aptos'
                paragraph.font.size = Pt(18)
                paragraph.font.color.rgb = RGBColor(255, 255, 255)
            if position + 1 < len(flow):
                arrow = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(9.45), Inches(y + .67), Inches(.35), Inches(.2))
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
