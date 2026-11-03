import assert from "node:assert/strict";
import test from "node:test";

import { getGovernanceInsightsState } from "../src/utils/governanceInsights.js";

test("governance insight section reports loading and API errors", () => {
  assert.equal(
    getGovernanceInsightsState({ insights: null, loading: true }),
    "loading",
  );
  assert.equal(
    getGovernanceInsightsState({
      insights: null,
      error: "Insights unavailable",
    }),
    "error",
  );
});

test("governance insight section distinguishes empty data from available data", () => {
  assert.equal(
    getGovernanceInsightsState({
      insights: { issue_counts: { unique_findings: 0 } },
    }),
    "empty",
  );
  assert.equal(
    getGovernanceInsightsState({
      insights: { issue_counts: { unique_findings: 3 } },
    }),
    "ready",
  );
  assert.equal(
    getGovernanceInsightsState({ insights: null }),
    "unavailable",
  );
});
