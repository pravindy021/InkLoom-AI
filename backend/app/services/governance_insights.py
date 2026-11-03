from collections import Counter, defaultdict
from typing import Any, Dict, Iterable


_RESOLVED_FINDING_STATES = {"closed", "dismissed", "resolved"}
_UNRESOLVED_FINDING_STATES = {"open", "pending"}


def build_governance_insights(
    finding_rows: Iterable[tuple],
    guideline_names: Dict[int, str],
    review_decisions: Iterable[tuple] = (),
    review_rows: Iterable[tuple] = (),
) -> Dict[str, Any]:
    """Build privacy-preserving aggregate signals from persisted review rows."""
    unique_findings = {}
    raw_finding_count = 0
    missing_timestamps = 0
    for row in finding_rows:
        (
            finding_id,
            review_id,
            guideline_id,
            category,
            severity,
            title,
            review_status,
            matched_text,
            created_at,
        ) = row
        raw_finding_count += 1
        if created_at is None:
            missing_timestamps += 1
        normalized_category = (category or "other").strip().casefold() or "other"
        normalized_title = (title or "").strip().casefold()
        normalized_text = (matched_text or "").strip().casefold()
        signature = (
            review_id,
            normalized_category,
            guideline_id,
            normalized_title,
            normalized_text,
        )
        unique_findings.setdefault(
            signature,
            {
                "id": finding_id,
                "review_id": review_id,
                "guideline_id": guideline_id,
                "category": normalized_category,
                "severity": (severity or "unknown").strip().casefold() or "unknown",
                "title": title or "",
                "review_status": (review_status or "unknown").strip().casefold(),
                "created_at": created_at,
            },
        )

    findings = list(unique_findings.values())
    categories = Counter()
    severities = Counter()
    finding_statuses = Counter()
    guideline_stats = defaultdict(lambda: {"finding_count": 0, "review_ids": set()})
    recurring_categories = defaultdict(lambda: {"finding_count": 0, "review_ids": set()})
    monthly = defaultdict(lambda: {"review_ids": set(), "finding_signatures": set()})
    for review_id, created_at in review_rows:
        if created_at is not None:
            monthly[created_at.strftime("%Y-%m")]["review_ids"].add(review_id)

    for finding, signature in zip(findings, unique_findings):
        categories[finding["category"]] += 1
        severities[finding["severity"]] += 1
        finding_statuses[finding["review_status"]] += 1
        recurring = recurring_categories[finding["category"]]
        recurring["finding_count"] += 1
        recurring["review_ids"].add(finding["review_id"])

        if finding["guideline_id"] is not None:
            stats = guideline_stats[finding["guideline_id"]]
            stats["finding_count"] += 1
            stats["review_ids"].add(finding["review_id"])

        created_at = finding["created_at"]
        if created_at is not None:
            month = created_at.strftime("%Y-%m")
            monthly[month]["review_ids"].add(finding["review_id"])
            monthly[month]["finding_signatures"].add(signature)

    repeated_categories = [
        {
            "category": category,
            "finding_count": stats["finding_count"],
            "review_count": len(stats["review_ids"]),
        }
        for category, stats in sorted(
            recurring_categories.items(),
            key=lambda item: (-len(item[1]["review_ids"]), item[0]),
        )
        if len(stats["review_ids"]) >= 2
    ]

    guideline_recurrence = []
    recommendations = []
    for guideline_id, stats in sorted(
        guideline_stats.items(),
        key=lambda item: (
            -len(item[1]["review_ids"]),
            -item[1]["finding_count"],
            item[0],
        ),
    ):
        review_count = len(stats["review_ids"])
        if review_count < 2:
            continue
        guideline_name = guideline_names.get(guideline_id)
        if not guideline_name:
            continue
        guideline_recurrence.append(
            {
                "guideline_id": guideline_id,
                "guideline": guideline_name,
                "finding_count": stats["finding_count"],
                "review_count": review_count,
            }
        )
        recommendations.append(
            {
                "type": "clarify_guideline",
                "title": "Review examples for a frequently triggered guideline",
                "message": (
                    "Consider clarifying “{0}” with an example or training note. "
                    "It was associated with findings across {1} separate reviews."
                ).format(guideline_name, review_count),
                "evidence": {
                    "guideline_id": guideline_id,
                    "finding_count": stats["finding_count"],
                    "review_count": review_count,
                },
            }
        )

    for item in repeated_categories:
        recommendations.append(
            {
                "type": "team_training",
                "title": "Address a recurring issue category",
                "message": (
                    "Consider a focused training or checklist for {0} issues, "
                    "which appeared in {1} separate reviews."
                ).format(item["category"].replace("_", " "), item["review_count"]),
                "evidence": item,
            }
        )

    months = sorted(monthly)
    review_decision_counts = Counter(
        status for status, _changed_at in review_decisions if status
    )
    resolved_count = sum(
        finding_statuses[state] for state in _RESOLVED_FINDING_STATES
    )
    unresolved_count = sum(
        finding_statuses[state] for state in _UNRESOLVED_FINDING_STATES
    )
    unknown_status_count = len(findings) - resolved_count - unresolved_count

    return {
        "issue_counts": {
            "unique_findings": len(findings),
            "duplicate_finding_records_ignored": max(
                0, raw_finding_count - len(findings)
            ),
            "by_category": [
                {"category": key, "count": value}
                for key, value in sorted(
                    categories.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "by_severity": dict(severities),
            "by_finding_status": dict(finding_statuses),
            "resolved": resolved_count,
            "unresolved": unresolved_count,
            "status_unknown": unknown_status_count,
        },
        "recurring_categories": repeated_categories,
        "guideline_recurrence": guideline_recurrence,
        "review_outcomes": {
            "changes_requested_events": review_decision_counts.get(
                "changes_requested", 0
            ),
            "approved_events": review_decision_counts.get("approved", 0),
            "interpretation": (
                "Review-level audit events are not attributable to a particular "
                "finding or guideline."
            ),
        },
        "trends_by_month": [
            {
                "month": month,
                "review_count": len(monthly[month]["review_ids"]),
                "unique_findings": len(monthly[month]["finding_signatures"]),
            }
            for month in months
        ],
        "recommendations": recommendations,
        "definitions": {
            "duplicate_rule": (
                "Exact duplicate finding records are deduplicated by review, "
                "category, guideline, title, and matched text."
            ),
            "recurrence_rule": (
                "A category or guideline is called recurring only when it appears "
                "in at least two distinct reviews."
            ),
            "time_basis": "Review creation timestamp, grouped by UTC calendar month.",
            "guideline_clarity": (
                "A recurrence signal suggests human review; it does not prove a "
                "guideline is unclear."
            ),
            "finding_resolution": (
                "Resolved counts include only explicit resolved/closed/dismissed "
                "finding statuses. Unknown statuses are reported separately."
            ),
        },
        "data_quality": {
            "finding_records": raw_finding_count,
            "unique_finding_records": len(findings),
            "missing_review_timestamps": missing_timestamps,
        },
    }
