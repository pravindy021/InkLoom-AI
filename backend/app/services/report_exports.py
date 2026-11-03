import csv
from datetime import datetime, timezone
from html import escape
from io import BytesIO, StringIO
from typing import Any, Dict, Iterable, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.risk_intelligence import calculate_risk

INK = colors.HexColor("#302A56")
VIOLET = colors.HexColor("#665BB8")
PALE = colors.HexColor("#F2F1FA")
GRID = colors.HexColor("#D9DCE5")


def _text(value: Any, limit: int = 12_000) -> str:
    if value is None:
        return "—"
    value = str(value).strip()
    return escape(value[:limit]).replace("\n", "<br/>") or "—"


def _date(value: Any) -> str:
    if not value:
        return "—"
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_text(value), style)


def _document(title: str):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.62 * inch,
        title=title,
        author="InkLoom AI",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="InkLoomTitle",
            parent=styles["Title"],
            textColor=INK,
            alignment=TA_CENTER,
            fontSize=20,
            leading=24,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            textColor=INK,
            fontSize=12,
            leading=15,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallBody",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallMuted",
            parent=styles["BodyText"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#626879"),
        )
    )
    return buffer, document, styles


def _footer(canvas, document):
    canvas.saveState()
    width, _height = letter
    canvas.setStrokeColor(GRID)
    canvas.line(0.65 * inch, 0.48 * inch, width - 0.65 * inch, 0.48 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#626879"))
    canvas.drawString(0.65 * inch, 0.31 * inch, "InkLoom AI · Confidential workspace report")
    canvas.drawRightString(width - 0.65 * inch, 0.31 * inch, "Page {}".format(document.page))
    canvas.restoreState()


def _table(rows: Iterable, widths, styles):
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def review_report_pdf(review, viewer, activities) -> bytes:
    comments = [
        comment
        for comment in review.comments
        if viewer.role in {"admin", "reviewer"} or not comment.is_internal
    ]
    findings = list(review.findings)
    finding_dicts = [
        {
            "category": item.category,
            "severity": item.severity,
            "title": item.title,
            "explanation": item.explanation,
            "matched_text": item.matched_text,
            "suggestion": item.suggestion,
            "confidence": item.confidence,
            "review_status": item.review_status,
            "guideline_id": item.guideline_id,
            **(item.metadata_json or {}),
        }
        for item in findings
    ]
    risk = calculate_risk(finding_dicts)
    severity_counts = {
        level: sum(1 for item in findings if item.severity == level)
        for level in ("critical", "high", "medium", "low")
    }

    buffer, document, styles = _document("Review {} report".format(review.id))
    body = [
        Paragraph("InkLoom AI", styles["InkLoomTitle"]),
        Paragraph("Review report", styles["Heading1"]),
        Paragraph(
            "Generated {} · Report for authorized workspace members".format(
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            ),
            styles["SmallMuted"],
        ),
        Spacer(1, 10),
        Paragraph("Project and review", styles["SectionHeading"]),
    ]
    review_rows = [
        ["Field", "Value"],
        ["Review ID", str(review.id)],
        ["Title", _paragraph(review.title, styles["SmallBody"])],
        ["Content type", _paragraph(review.content_type, styles["SmallBody"])],
        ["Status", _paragraph(review.status, styles["SmallBody"])],
        ["Submitted", _paragraph(_date(review.created_at), styles["SmallBody"])],
        ["Analysis updated", _paragraph(_date(review.analysis_timestamp), styles["SmallBody"])],
        ["Risk score", "{}/100 ({})".format(risk["score"], risk["level"])],
        ["Detected issues", str(len(findings))],
    ]
    body.extend(
        [
            _table(review_rows, [1.35 * inch, 5.85 * inch], styles),
            Paragraph("Severity breakdown", styles["SectionHeading"]),
            _table(
                [["Critical", "High", "Medium", "Low"]]
                + [[str(severity_counts[level]) for level in ("critical", "high", "medium", "low")]],
                [1.8 * inch] * 4,
                styles,
            ),
            Paragraph("Submitted content", styles["SectionHeading"]),
            _paragraph(review.content, styles["SmallBody"]),
            Paragraph("Findings", styles["SectionHeading"]),
        ]
    )
    if findings:
        rows = [[
            _paragraph("Severity / status", styles["SmallBody"]),
            _paragraph("Finding and explanation", styles["SmallBody"]),
            _paragraph("Guideline / evidence / suggestion", styles["SmallBody"]),
        ]]
        for finding in findings:
            metadata = finding.metadata_json or {}
            visual_data = metadata.get("visual_data") or {}
            timestamp = visual_data.get("timestamp_seconds")
            title = finding.title
            if timestamp is not None:
                title = "[{}] {}".format(_format_timestamp(timestamp), title)
            citations = metadata.get("citations") or []
            refs = [
                str(item.get("name") or item.get("source_id") or "Evidence")
                for item in citations[:8]
                if isinstance(item, dict)
            ]
            refs_text = "Evidence: {}".format(", ".join(refs)) if refs else ""
            guideline_reference = finding.source or (
                "Guideline #{}".format(finding.guideline_id)
                if finding.guideline_id
                else "Not supplied"
            )
            guidance = "Guideline: {}".format(guideline_reference)
            suggestion = "Suggestion: {}".format(finding.suggestion or "None supplied")
            rows.append(
                [
                    _paragraph(
                        "{} / {}".format(finding.severity, finding.review_status),
                        styles["SmallBody"],
                    ),
                    _paragraph(
                        "{}<br/><br/>{}<br/><br/>Matched: {}".format(
                            title, finding.explanation, finding.matched_text or "—"
                        ),
                        styles["SmallBody"],
                    ),
                    _paragraph(
                        "{}<br/>{}<br/>{}".format(guidance, refs_text, suggestion),
                        styles["SmallBody"],
                    ),
                ]
            )
        body.append(_table(rows, [1.05 * inch, 3.35 * inch, 2.8 * inch], styles))
    else:
        body.append(Paragraph("No findings were recorded for this review.", styles["SmallBody"]))

    attachment = review.visual_attachment
    video = (attachment.analysis_metadata or {}).get("video") if attachment else None
    if video:
        body.append(Paragraph("Video review", styles["SectionHeading"]))
        body.append(
            Paragraph(
                "Duration: {} seconds · Extracted frames: {}".format(
                    video.get("duration_seconds", "unknown"),
                    len(video.get("frames") or []),
                ),
                styles["SmallBody"],
            )
        )
        transcript = video.get("transcript") or {}
        segments = transcript.get("segments") or []
        if segments:
            transcript_rows = [[
                _paragraph("Time", styles["SmallBody"]),
                _paragraph("Transcript segment", styles["SmallBody"]),
            ]]
            transcript_rows.extend(
                [
                    _paragraph(_format_timestamp(segment.get("start", 0)), styles["SmallBody"]),
                    _paragraph(segment.get("text", ""), styles["SmallBody"]),
                ]
                for segment in segments
            )
            body.extend(
                [
                    Paragraph("Timestamped transcript", styles["Heading3"]),
                    _table(transcript_rows, [0.8 * inch, 6.4 * inch], styles),
                ]
            )
        elif transcript.get("text"):
            body.append(_paragraph(transcript["text"], styles["SmallBody"]))
        warnings = video.get("warnings") or []
        if warnings:
            body.append(_paragraph("Processing notes: " + " ".join(warnings), styles["SmallMuted"]))

    body.append(Paragraph("Reviewer comments", styles["SectionHeading"]))
    if comments:
        comment_rows = [[
            _paragraph("Author / date", styles["SmallBody"]),
            _paragraph("Comment", styles["SmallBody"]),
        ]]
        comment_rows.extend(
            [
                _paragraph(
                    "{} · {}".format(comment.author or "Unknown", _date(comment.created_at)),
                    styles["SmallBody"],
                ),
                _paragraph(comment.comment, styles["SmallBody"]),
            ]
            for comment in comments
        )
        body.append(_table(comment_rows, [1.6 * inch, 5.6 * inch], styles))
    else:
        body.append(Paragraph("No visible comments are recorded.", styles["SmallBody"]))

    body.append(Paragraph("Human approval decisions", styles["SectionHeading"]))
    decisions = list(review.approval_decisions)
    if decisions:
        decision_rows = [[
            _paragraph("Reviewer", styles["SmallBody"]),
            _paragraph("Decision / version", styles["SmallBody"]),
            _paragraph("Reason / date", styles["SmallBody"]),
        ]]
        decision_rows.extend(
            [
                _paragraph(decision.reviewer.display_name if decision.reviewer else "Unknown", styles["SmallBody"]),
                _paragraph("{} / {}".format(decision.decision, decision.version_id), styles["SmallBody"]),
                _paragraph("{} · {}".format(decision.reason or "No reason supplied", _date(decision.created_at)), styles["SmallBody"]),
            ]
            for decision in decisions
        )
        body.append(_table(decision_rows, [1.4 * inch, 1.5 * inch, 4.3 * inch], styles))
    else:
        body.append(Paragraph("No formal approval decision is recorded.", styles["SmallBody"]))

    body.append(Paragraph("Revision history", styles["SectionHeading"]))
    revisions = list(review.revisions)
    if revisions:
        revision_rows = [[
            _paragraph("Revision", styles["SmallBody"]),
            _paragraph("Author / date", styles["SmallBody"]),
            _paragraph("Content", styles["SmallBody"]),
        ]]
        revision_rows.extend(
            [
                _paragraph(revision.title or "Revision {}".format(revision.id), styles["SmallBody"]),
                _paragraph("{} · {}".format(revision.author.display_name if revision.author else "Unknown", _date(revision.created_at)), styles["SmallBody"]),
                _paragraph(revision.content, styles["SmallBody"]),
            ]
            for revision in revisions
        )
        body.append(_table(revision_rows, [1.3 * inch, 1.7 * inch, 4.2 * inch], styles))
    else:
        body.append(Paragraph("No revisions are recorded.", styles["SmallBody"]))

    body.append(Paragraph("Audit activity", styles["SectionHeading"]))
    if activities:
        activity_rows = [[
            _paragraph("Date", styles["SmallBody"]),
            _paragraph("Actor / action", styles["SmallBody"]),
            _paragraph("Details", styles["SmallBody"]),
        ]]
        activity_rows.extend(
            [
                _paragraph(_date(activity.created_at), styles["SmallBody"]),
                _paragraph("{} / {}".format(activity.actor or "System", activity.action), styles["SmallBody"]),
                _paragraph(activity.details or {}, styles["SmallBody"]),
            ]
            for activity in activities
        )
        body.append(_table(activity_rows, [1.45 * inch, 1.75 * inch, 4.0 * inch], styles))
    else:
        body.append(Paragraph("No audit activity is recorded.", styles["SmallBody"]))

    document.build(body, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _format_timestamp(value: Any) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        seconds = 0
    return "{:02d}:{:02d}:{:02d}".format(
        seconds // 3600, (seconds % 3600) // 60, seconds % 60
    )


def analytics_rows(summary: Dict[str, Any], blind_spots: Iterable[Dict[str, Any]]):
    rows = [
        ["section", "metric", "value"],
        ["date_range", "start_date", summary["date_range"]["start_date"] or "all"],
        ["date_range", "end_date", summary["date_range"]["end_date"] or "all"],
        ["reviews", "total_reviews", summary["total_reviews"]],
        ["reviews", "pending_approvals", summary["pending_approvals"]],
        ["findings", "total_issues", summary["total_issues"]],
    ]
    rows.extend(
        ["severity", severity, count]
        for severity, count in summary["issues_by_severity"].items()
    )
    rows.extend(
        ["category", item["category"], item["count"]]
        for item in summary["issues_by_category"]
    )
    rows.extend(
        ["review_status", item["status"], item["count"]]
        for item in summary["status_distribution"]
    )
    rows.extend(
        ["recurring_guideline", item["name"], item["count"]]
        for item in summary["frequent_guidelines"]
    )
    rows.extend(
        ["guideline_trend", item.get("guideline", "Unknown"), item.get("mentions", 0)]
        for item in blind_spots
    )
    rows.extend(
        ["reviewer_activity", item["reviewer"], item["decisions"]]
        for item in summary["reviewer_activity"]
    )
    rows.extend(
        ["claim_verification", status, count]
        for status, count in summary["claim_verification_statuses"].items()
    )
    rows.extend(
        ["risk_distribution", level, count]
        for level, count in summary.get("risk_distribution", {}).items()
    )
    return rows


def analytics_csv(summary: Dict[str, Any], blind_spots: Iterable[Dict[str, Any]]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    for row in analytics_rows(summary, blind_spots):
        writer.writerow([_spreadsheet_safe(value) for value in row])
    return output.getvalue().encode("utf-8-sig")


def _spreadsheet_safe(value: Any):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def analytics_report_pdf(summary: Dict[str, Any], blind_spots: Iterable[Dict[str, Any]]) -> bytes:
    buffer, document, styles = _document("InkLoom AI analytics report")
    body = [
        Paragraph("InkLoom AI", styles["InkLoomTitle"]),
        Paragraph("Workspace analytics report", styles["Heading1"]),
        Paragraph(
            "Generated {} · Date range: {} to {}".format(
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                summary["date_range"]["start_date"] or "All time",
                summary["date_range"]["end_date"] or "All time",
            ),
            styles["SmallMuted"],
        ),
        Paragraph("Review statistics", styles["SectionHeading"]),
        _table(
            [
                ["Metric", "Value"],
                ["Total reviews", str(summary["total_reviews"])],
                ["Detected issues", str(summary["total_issues"])],
                ["Pending approvals", str(summary["pending_approvals"])],
                [
                    "Average review time",
                    (
                        "{} hours".format(summary["average_review_time_hours"])
                        if summary["average_review_time_hours"] is not None
                        else "Not available"
                    ),
                ],
            ],
            [3.6 * inch, 3.6 * inch],
            styles,
        ),
        Paragraph("Issue severity", styles["SectionHeading"]),
        _table(
            [["Severity", "Count"]]
            + [
                [level.title(), str(count)]
                for level, count in summary["issues_by_severity"].items()
            ],
            [3.6 * inch, 3.6 * inch],
            styles,
        ),
        Paragraph("Recurring issue categories", styles["SectionHeading"]),
    ]
    categories = summary["issues_by_category"]
    body.append(
        _table(
            [["Category", "Count"]]
            + [[_paragraph(item["category"], styles["SmallBody"]), str(item["count"])] for item in categories],
            [5.4 * inch, 1.8 * inch],
            styles,
        )
        if categories
        else Paragraph("No category data is available for this range.", styles["SmallBody"])
    )
    guideline_rows = [["Guideline / trend", "Count or mentions"]]
    guideline_rows.extend(
        [_paragraph(item["name"], styles["SmallBody"]), str(item["count"])]
        for item in summary["frequent_guidelines"]
    )
    guideline_rows.extend(
        [_paragraph(item.get("guideline", "Unknown"), styles["SmallBody"]), str(item.get("mentions", 0))]
        for item in blind_spots
    )
    body.extend(
        [
            Paragraph("Guideline trends", styles["SectionHeading"]),
            _table(guideline_rows, [5.4 * inch, 1.8 * inch], styles),
            Paragraph("Reviewer activity", styles["SectionHeading"]),
        ]
    )
    reviewers = summary["reviewer_activity"]
    body.append(
        _table(
            [["Reviewer", "Recorded decisions"]]
            + [[_paragraph(item["reviewer"], styles["SmallBody"]), str(item["decisions"])] for item in reviewers],
            [5.4 * inch, 1.8 * inch],
            styles,
        )
        if reviewers
        else Paragraph("No reviewer activity is recorded for this range.", styles["SmallBody"])
    )
    risk = summary.get("risk_distribution") or {}
    body.extend(
        [
            Paragraph("Review risk distribution", styles["SectionHeading"]),
            _table(
                [["Risk level", "Reviews"]]
                + [[level.title(), str(count)] for level, count in risk.items()],
                [3.6 * inch, 3.6 * inch],
                styles,
            ),
            Paragraph(
                "Risk scores are advisory estimates derived from recorded findings; they are not approval decisions or factual proof.",
                styles["SmallMuted"],
            ),
        ]
    )
    document.build(body, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
