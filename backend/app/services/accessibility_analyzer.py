from io import BytesIO
import re
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
import zipfile


_GENERIC_LINK_LABELS = {
    "click here",
    "here",
    "learn more",
    "link",
    "more",
    "read more",
    "this link",
}
_MARKDOWN_HEADING = re.compile(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_HTML_HEADING = re.compile(
    r"(?is)<h([1-6])\b[^>]*>(.*?)</h\1\s*>"
)
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_HTML_LINK = re.compile(r"(?is)<a\b[^>]*>(.*?)</a\s*>")
_HTML_TAG = re.compile(r"<[^>]*>")


def _plain_text(value: str) -> str:
    return unescape(_HTML_TAG.sub(" ", value)).strip()


def _finding(
    title: str,
    explanation: str,
    suggestion: str,
    evidence: str,
    method: str,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "category": "accessibility",
        "severity": "low",
        "title": title,
        "explanation": explanation,
        "matched_text": evidence or None,
        "suggestion": suggestion,
        "source": method,
        "guideline": None,
        "guideline_id": None,
        "confidence": confidence,
        "detection_method": method,
    }


def _heading_levels(text: str) -> List[Tuple[int, int, str]]:
    headings = [
        (match.start(), len(match.group(1)), match.group(2).strip())
        for match in _MARKDOWN_HEADING.finditer(text)
    ]
    headings.extend(
        (match.start(), int(match.group(1)), _plain_text(match.group(2)))
        for match in _HTML_HEADING.finditer(text)
    )
    return sorted(headings)


def _structured_link_labels(text: str) -> Tuple[List[Tuple[int, int, str]], List[Tuple[int, int]]]:
    links: List[Tuple[int, int, str]] = []
    spans: List[Tuple[int, int]] = []
    for pattern in (_MARKDOWN_LINK, _HTML_LINK):
        for match in pattern.finditer(text):
            label = (
                match.group(1)
                if pattern is _MARKDOWN_LINK
                else _plain_text(match.group(1))
            )
            links.append((match.start(), match.end(), label.strip()))
            spans.append((match.start(), match.end()))
    return sorted(links), spans


def analyze_text_accessibility(text: str) -> List[Dict[str, Any]]:
    """Check explicit text markup and flag very long English prose heuristically."""
    findings: List[Dict[str, Any]] = []
    headings = _heading_levels(text)
    previous_level = None
    for _position, level, title in headings:
        if previous_level is not None and level > previous_level + 1:
            findings.append(
                _finding(
                    "Heading hierarchy skips a level",
                    "The document moves from heading level {0} to level {1}, which may make its structure harder to navigate.".format(
                        previous_level, level
                    ),
                    "Use the next heading level in sequence, or reorganize the section hierarchy.",
                    title,
                    "Deterministic heading-level sequence check",
                    1.0,
                )
            )
        previous_level = level

    links, link_spans = _structured_link_labels(text)
    for _start, _end, label in links:
        normalized = re.sub(r"\s+", " ", label).strip().casefold()
        if not normalized or normalized in _GENERIC_LINK_LABELS:
            findings.append(
                _finding(
                    "Link text is missing or unclear",
                    "A link has no visible text or uses a generic label that does not describe its destination.",
                    "Give the link a concise label that describes its destination or action.",
                    label or "[link with no text]",
                    "Deterministic HTML/Markdown link-label check",
                    1.0,
                )
            )

    for match in re.finditer(r"\bclick\s+here\b", text, re.IGNORECASE):
        if any(start <= match.start() < end for start, end in link_spans):
            continue
        findings.append(
            _finding(
                "Non-descriptive link wording",
                "“Click here” does not describe the destination and can be less useful to assistive-technology users.",
                "Replace it with a concise link label that describes the destination or action.",
                match.group(0),
                "Deterministic wording check",
                1.0,
            )
        )

    readable_text = _plain_text(text)
    readable_text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", readable_text)
    words = re.findall(r"\b[\w'-]+\b", readable_text)
    sentences = [
        sentence
        for sentence in re.split(r"[.!?]+", readable_text)
        if re.search(r"\w", sentence)
    ]
    if len(words) >= 100 and len(sentences) >= 3:
        average_sentence_length = len(words) / len(sentences)
        if average_sentence_length > 25:
            findings.append(
                _finding(
                    "Long sentences may reduce readability",
                    "The text averages {0:.1f} words per sentence. Sentence length is a readability signal, not a measure of comprehension.".format(
                        average_sentence_length
                    ),
                    "Consider splitting long sentences and checking the copy with its intended audience.",
                    "{0} words across {1} sentences".format(
                        len(words), len(sentences)
                    ),
                    "Advisory sentence-length heuristic",
                    None,
                )
            )
    return findings


def analyze_docx_accessibility(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Inspect accessibility metadata exposed by python-docx; do not infer missing structure."""
    try:
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        from lxml.etree import XMLSyntaxError
    except ImportError as exc:
        raise ValueError(
            "DOCX accessibility inspection dependencies are unavailable."
        ) from exc

    try:
        document = Document(BytesIO(file_bytes))
    except (
        KeyError,
        OSError,
        PackageNotFoundError,
        ValueError,
        XMLSyntaxError,
        zipfile.BadZipFile,
    ) as exc:
        raise ValueError("The uploaded DOCX document could not be inspected.") from exc

    findings: List[Dict[str, Any]] = []
    previous_level = None
    for paragraph in document.paragraphs:
        style = paragraph.style
        style_name = getattr(style, "name", "") or ""
        style_id = getattr(style, "style_id", "") or ""
        match = re.fullmatch(r"Heading\s*([1-6])", style_name, re.IGNORECASE)
        if not match:
            match = re.fullmatch(r"Heading([1-6])", style_id, re.IGNORECASE)
        if match:
            level = int(match.group(1))
            if previous_level is not None and level > previous_level + 1:
                findings.append(
                    _finding(
                        "Heading hierarchy skips a level",
                        "The DOCX moves from heading level {0} to level {1}, which may make its structure harder to navigate.".format(
                            previous_level, level
                        ),
                        "Use the next heading level in sequence, or reorganize the section hierarchy.",
                        paragraph.text.strip(),
                        "Deterministic DOCX heading-style sequence check",
                        1.0,
                    )
                )
            previous_level = level

        for hyperlink in paragraph._p.xpath(".//w:hyperlink"):
            label = "".join(
                node.text or "" for node in hyperlink.xpath(".//w:t")
            ).strip()
            normalized = re.sub(r"\s+", " ", label).casefold()
            if not normalized or normalized in _GENERIC_LINK_LABELS:
                findings.append(
                    _finding(
                        "Link text is missing or unclear",
                        "A DOCX hyperlink has no visible text or uses a generic label that does not describe its destination.",
                        "Give the link a concise label that describes its destination or action.",
                        label or "[link with no text]",
                        "Deterministic DOCX hyperlink-label check",
                        1.0,
                    )
                )

    for index, shape in enumerate(document.inline_shapes, start=1):
        description = (shape._inline.docPr.get("descr") or "").strip()
        if not description:
            findings.append(
                _finding(
                    "Document image alternative text not provided",
                    "An embedded DOCX image has no alternative-text description in its document metadata.",
                    "Add alternative text describing the image's relevant content or purpose.",
                    "Inline image {0}".format(index),
                    "Deterministic DOCX image-description metadata check",
                    1.0,
                )
            )

    return findings
