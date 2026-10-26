from typing import Optional


def terminology_suggestion(term: str, preferred_term: Optional[str]) -> str:
    if preferred_term:
        return "Replace “{}” with “{}” to use the approved terminology.".format(
            term, preferred_term
        )
    return "Review “{}” and replace it with the preferred wording in your brand guidelines.".format(
        term
    )


def claim_suggestion(matched_text: str) -> str:
    return (
        "Revise “{}” to a specific, supportable statement and include evidence "
        "where the claim requires substantiation."
    ).format(matched_text)


def factual_suggestion() -> str:
    return (
        "Verify this statement against a current, approved source before publication; "
        "do not present it as verified without evidence."
    )
