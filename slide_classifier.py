"""Classify a ParsedSlide into one of five SlideType categories (no LLM call)."""
from __future__ import annotations

import re
from enum import Enum

from slide_parser import ParsedSlide

_CODE_PUNCT_RE = re.compile(r"[{};()\[\]<>]")
_CODE_KEYWORD_RE = re.compile(
    r"\b(def |class |import |from |function |const |return |var |let )"
)
_DIAGRAM_KEYWORD_RE = re.compile(
    r"\b(flowchart|architecture|sequence|erd|uml|pipeline|workflow|diagram)\b",
    re.IGNORECASE,
)


class SlideType(str, Enum):
    TITLE = "title"
    CONCEPT = "concept"
    CODE = "code"
    DIAGRAM = "diagram"
    IMAGE_HEAVY = "image_heavy"


def classify(slide: ParsedSlide) -> SlideType:
    text = slide.body_text
    word_count = len(text.split())
    img_count = len(slide.embedded_images)

    # TITLE: first slide, or very short title with no body
    if slide.slide_index == 0:
        return SlideType.TITLE
    if slide.title and len(slide.title) < 30 and not text.strip():
        return SlideType.TITLE

    # CODE: high punctuation density or keyword presence
    if len(text) > 0:
        punct_ratio = len(_CODE_PUNCT_RE.findall(text)) / len(text)
        if punct_ratio > 0.05 or _CODE_KEYWORD_RE.search(text):
            return SlideType.CODE

    # DIAGRAM: single image with explicit diagram-keyword cues (more specific than IMAGE_HEAVY)
    if img_count == 1 and _DIAGRAM_KEYWORD_RE.search(text):
        return SlideType.DIAGRAM

    # IMAGE_HEAVY: dominated by images with little text
    if img_count >= 2 or (img_count == 1 and word_count < 20):
        return SlideType.IMAGE_HEAVY

    # CONCEPT: everything else
    return SlideType.CONCEPT
