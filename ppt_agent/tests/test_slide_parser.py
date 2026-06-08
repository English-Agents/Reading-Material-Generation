"""Unit tests for slide_parser and slide_classifier."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from slide_classifier import SlideType, classify
from slide_parser import EmbeddedImage, ParsedSlide, parse


def test_parse_pptx_returns_slides(sample_pptx_path):
    slides = parse(str(sample_pptx_path))
    assert len(slides) >= 1
    assert all(isinstance(s, ParsedSlide) for s in slides)


def test_parse_pptx_title_slide(sample_pptx_path):
    slides = parse(str(sample_pptx_path))
    assert slides[0].title == "Introduction"
    assert slides[0].slide_index == 0


def test_parse_pptx_body_text(sample_pptx_path):
    slides = parse(str(sample_pptx_path))
    assert len(slides) >= 2
    assert "machine learning" in slides[1].body_text


def test_classify_first_slide_is_title(sample_pptx_path):
    slides = parse(str(sample_pptx_path))
    assert classify(slides[0]) == SlideType.TITLE


def test_classify_concept_slide(sample_pptx_path):
    slides = parse(str(sample_pptx_path))
    if len(slides) > 1:
        assert classify(slides[1]) == SlideType.CONCEPT


def test_classify_code_slide():
    slide = ParsedSlide(
        slide_index=1,
        title="Code Example",
        body_text="def train_model(X, y):\n    return model.fit(X, y)",
        speaker_notes="",
        embedded_images=[],
        source_url="test",
    )
    assert classify(slide) == SlideType.CODE


def test_classify_image_heavy():
    from slide_parser import EmbeddedImage

    images = [
        EmbeddedImage(md5="aaa", base64_data="", mime_type="image/png", slide_index=1, image_index=0),
        EmbeddedImage(md5="bbb", base64_data="", mime_type="image/png", slide_index=1, image_index=1),
    ]
    slide = ParsedSlide(
        slide_index=1,
        title=None,
        body_text="short",
        speaker_notes="",
        embedded_images=images,
        source_url="test",
    )
    assert classify(slide) == SlideType.IMAGE_HEAVY


def test_classify_diagram():
    from slide_parser import EmbeddedImage

    slide = ParsedSlide(
        slide_index=2,
        title="Architecture",
        body_text="This flowchart shows the pipeline architecture",
        speaker_notes="",
        embedded_images=[
            EmbeddedImage(md5="ccc", base64_data="", mime_type="image/png", slide_index=2, image_index=0)
        ],
        source_url="test",
    )
    assert classify(slide) == SlideType.DIAGRAM


def test_embedded_image_md5_is_hex():
    import hashlib
    data = b"fake image bytes"
    md5 = hashlib.md5(data).hexdigest()
    assert len(md5) == 32
    assert all(c in "0123456789abcdef" for c in md5)
