import assert from "node:assert/strict";
import test from "node:test";

import {
  canManageVisualBrandPalette,
  loadVisualBrandData,
  normalizeHexColor,
  validateVisualBrandPalette,
} from "../src/utils/visualBrandPalette.js";
import { mockApi } from "../src/services/mockApi.js";

test("validates and normalizes six-digit HEX colors", () => {
  assert.equal(normalizeHexColor("#a1b2c3"), "#A1B2C3");
  assert.equal(normalizeHexColor("#12345"), null);
  assert.equal(normalizeHexColor("red"), null);
  assert.equal(
    validateVisualBrandPalette({
      primary: ["#aabbcc"],
      secondary: [],
      accent: ["#F0A020"],
    }).valid,
    true,
  );
});

test("rejects malformed, duplicate, and excessive palette colors", () => {
  assert.equal(
    validateVisualBrandPalette({
      primary: ["#12345"],
      secondary: [],
      accent: [],
    }).errors.primary.includes("six-digit"),
    true,
  );
  assert.equal(
    validateVisualBrandPalette({
      primary: ["#123456"],
      secondary: ["#123456"],
      accent: [],
    }).errors.duplicates.includes("once"),
    true,
  );
  assert.equal(
    validateVisualBrandPalette({
      primary: Array.from({ length: 11 }, (_, index) =>
        `#${String(index).padStart(6, "0")}`,
      ),
      secondary: [],
      accent: [],
    }).errors.primary.includes("10"),
    true,
  );
});

test("only Admin role can manage the visual brand palette", () => {
  assert.equal(canManageVisualBrandPalette("admin"), true);
  assert.equal(canManageVisualBrandPalette("reviewer"), false);
  assert.equal(canManageVisualBrandPalette("contributor"), false);
  assert.equal(canManageVisualBrandPalette("demo"), false);
});

test("palette loader calls configuration and history endpoints and sorts history", async () => {
  const calls = [];
  const result = await loadVisualBrandData({
    async visualBrandPalette() {
      calls.push("palette");
      return {
        primary: ["#abcdef"],
        secondary: [],
        accent: [],
        version_number: 2,
      };
    },
    async visualBrandPaletteVersions() {
      calls.push("versions");
      return [
        { version_number: 1, snapshot: { primary: ["#000000"] } },
        { version_number: 2, snapshot: { primary: ["#ABCDEF"] } },
      ];
    },
  });

  assert.deepEqual(calls.sort(), ["palette", "versions"]);
  assert.deepEqual(result.palette.primary, ["#ABCDEF"]);
  assert.deepEqual(
    result.versions.map((version) => version.version_number),
    [2, 1],
  );
});

test("palette loader propagates API errors for the page error state", async () => {
  const expectedError = new Error("Palette API unavailable");
  await assert.rejects(
    loadVisualBrandData({
      visualBrandPalette: async () => {
        throw expectedError;
      },
      visualBrandPaletteVersions: async () => [],
    }),
    expectedError,
  );
});

test("mock palette API saves changes and exposes editor history", async () => {
  const before = await mockApi.visualBrandPalette();
  const saved = await mockApi.updateVisualBrandPalette({
    primary: ["#AABBCC"],
    secondary: ["#123456"],
    accent: [],
  });
  const current = await mockApi.visualBrandPalette();
  const history = await mockApi.visualBrandPaletteVersions();

  assert.equal(saved.version_number, before.version_number + 1);
  assert.deepEqual(current.primary, ["#AABBCC"]);
  assert.equal(history[0].editor, "Mock workspace");
  assert.deepEqual(history[0].snapshot.secondary, ["#123456"]);
});
