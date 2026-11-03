export function getGovernanceInsightsState({
  insights,
  error = "",
  loading = false,
}) {
  if (loading) return "loading";
  if (error) return "error";
  if (!insights || typeof insights !== "object") return "unavailable";
  return Number(insights.issue_counts?.unique_findings) > 0
    ? "ready"
    : "empty";
}
