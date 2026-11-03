import assert from "node:assert/strict";
import test from "node:test";

import { api } from "../src/services/api.js";
import { mockApi } from "../src/services/mockApi.js";
import { canArchiveReview } from "../src/utils/reviewArchive.js";

test("archive actions are restricted to Admin in the frontend", () => {
  assert.equal(canArchiveReview("admin"), true);
  assert.equal(canArchiveReview("reviewer"), false);
  assert.equal(canArchiveReview("contributor"), false);
  assert.equal(canArchiveReview(undefined), false);
});

test("deleteReview uses the existing review resource with DELETE", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response('{"id":42}', { status: 200 });
  };

  try {
    const result = await api.deleteReview(42);
    assert.deepEqual(result, { id: 42 });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(request.url, "http://localhost:8000/api/reviews/42");
  assert.equal(request.options.method, "DELETE");
});

test("mock archive removes a review from normal listings and retains its record", async () => {
  const before = await mockApi.reviews({ limit: 100 });
  const item = before.items[0];
  const originalContent = item.content;

  const result = await mockApi.deleteReview(item.id);
  const after = await mockApi.reviews({ limit: 100 });
  const archived = await mockApi.review(item.id);

  assert.equal(result.id, item.id);
  assert.equal(after.items.some((review) => review.id === item.id), false);
  assert.equal(archived.content, originalContent);
  assert.equal(archived.activity.at(-1).action, "review_archived");
  assert.equal(archived.activity.at(-1).actor, "Mock Admin");
});
