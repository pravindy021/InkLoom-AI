/**
 * Safely apply a finding's suggestion to a draft.
 *
 * Instruction-style suggestions are not replacement text. Only apply
 * a replacement when the finding provides a clearly identifiable term.
 * Ambiguous excerpts are never replaced automatically.
 */

export function getSafeReplacement(matchedText, suggestion, category = "") {
  if (
    typeof matchedText !== "string" ||
    typeof suggestion !== "string" ||
    !matchedText.trim() ||
    !suggestion.trim()
  ) {
    return { ok: false, reason: "missing-text" };
  }

  // Only terminology findings have a supported, explicit replacement pattern.
  if (String(category).toLowerCase() === "terminology") {
    const escapedMatch = matchedText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(
      `^\\s*Replace\\s+["“]${escapedMatch}["”]\\s+with\\s+["“]([^"“”]+)["”]`,
      "i",
    );
    const result = suggestion.match(pattern);

    if (result?.[1]?.trim()) {
      return { ok: true, replacement: result[1].trim() };
    }
  }

  return { ok: false, reason: "manual-edit-required" };
}

export function applySuggestionToContent(content, matchedText, suggestion) {
  if (
    typeof content !== "string" ||
    typeof matchedText !== "string" ||
    typeof suggestion !== "string"
  ) {
    return { ok: false, reason: "invalid-input" };
  }

  if (!matchedText.length || !suggestion.length) {
    return { ok: false, reason: "missing-text" };
  }

  const firstIndex = content.indexOf(matchedText);
  if (firstIndex === -1) {
    return { ok: false, reason: "not-found" };
  }

  // Search from the next character so overlapping matches are also detected.
  if (content.indexOf(matchedText, firstIndex + 1) !== -1) {
    return { ok: false, reason: "ambiguous" };
  }

  return {
    ok: true,
    content:
      content.slice(0, firstIndex) +
      suggestion +
      content.slice(firstIndex + matchedText.length),
  };
}
