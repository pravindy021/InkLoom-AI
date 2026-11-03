import assert from "node:assert/strict";
import test from "node:test";

import { api } from "../src/services/api.js";

test("JSON analysis and revision requests propagate per-analysis remote AI consent", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response("{}", { status: 200 });
  };

  try {
    await api.analyze({
      title: "Consent check",
      content: "A local draft.",
      content_type: "Email",
      allow_external_ai_processing: false,
    });
    await api.reanalyze(14, {
      content: "A revised draft.",
      allow_external_ai_processing: true,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    JSON.parse(requests[0].options.body).allow_external_ai_processing,
    false,
  );
  assert.equal(
    JSON.parse(requests[1].options.body).allow_external_ai_processing,
    true,
  );
});

test("only boolean true grants remote AI consent in JSON requests", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response("{}", { status: 200 });
  };
  const values = [
    undefined,
    false,
    null,
    "true",
    "false",
    "yes",
    1,
    0,
    {},
  ];

  try {
    for (const value of values) {
      await api.analyze({
        title: "Consent coercion check",
        content: "A draft.",
        content_type: "Email",
        allow_external_ai_processing: value,
      });
      await api.reanalyze(14, {
        content: "A revised draft.",
        allow_external_ai_processing: value,
      });
    }
    await api.analyze({
      title: "Explicit consent check",
      content: "A draft.",
      content_type: "Email",
      allow_external_ai_processing: true,
    });
    await api.reanalyze(14, {
      content: "An explicitly opted-in revision.",
      allow_external_ai_processing: true,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  for (const request of requests.slice(0, values.length * 2)) {
    assert.equal(
      JSON.parse(request.options.body).allow_external_ai_processing,
      false,
    );
  }
  for (const request of requests.slice(values.length * 2)) {
    assert.equal(
      JSON.parse(request.options.body).allow_external_ai_processing,
      true,
    );
  }
});

test("multipart analysis propagates remote AI consent", async () => {
  const originalXhr = globalThis.XMLHttpRequest;
  let submittedForm;

  class MockXMLHttpRequest {
    constructor() {
      this.upload = { addEventListener() {} };
      this.listeners = {};
      this.status = 200;
      this.responseText = "{}";
    }

    open() {}
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    }
    send(form) {
      submittedForm = form;
      this.listeners.load();
    }
  }

  globalThis.XMLHttpRequest = MockXMLHttpRequest;
  try {
    await api.analyze({
      title: "Uploaded consent check",
      content: "A local draft.",
      content_type: "Email",
      file: new Blob(["image payload"], { type: "image/png" }),
      allow_external_ai_processing: true,
    });
  } finally {
    globalThis.XMLHttpRequest = originalXhr;
  }

  assert.equal(submittedForm.get("allow_external_ai_processing"), "true");
});

test("only boolean true grants remote AI consent in multipart requests", async () => {
  const originalXhr = globalThis.XMLHttpRequest;
  const submittedForms = [];

  class MockXMLHttpRequest {
    constructor() {
      this.upload = { addEventListener() {} };
      this.listeners = {};
      this.status = 200;
      this.responseText = "{}";
    }

    open() {}
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    }
    send(form) {
      submittedForms.push(form);
      this.listeners.load();
    }
  }

  globalThis.XMLHttpRequest = MockXMLHttpRequest;
  try {
    for (const value of [
      undefined,
      false,
      null,
      "true",
      "false",
      "yes",
      1,
      0,
      {},
      true,
    ]) {
      await api.analyze({
        title: "Multipart consent check",
        content: "A draft.",
        content_type: "Email",
        file: new Blob(["image payload"], { type: "image/png" }),
        allow_external_ai_processing: value,
      });
    }
  } finally {
    globalThis.XMLHttpRequest = originalXhr;
  }

  assert.deepEqual(
    submittedForms.map((form) => form.get("allow_external_ai_processing")),
    ["false", "false", "false", "false", "false", "false", "false", "false", "false", "true"],
  );
});
