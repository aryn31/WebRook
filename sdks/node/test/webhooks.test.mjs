import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { verify, verifySignature, sign, WebhookVerificationError } from "../dist/esm/index.js";
import { API_DOCS, BACKEND_SIGNING, backendSign, buildBody, hasBackend, hasDocs } from "./helpers.mjs";

const SECRET = "whsec_9f8e7d6c5b4a39281706f5e4d3c2b1a0";
const OLD_SECRET = "whsec_old0000000000000000000000000000";
const NOW = 1_793_361_600;
const BODY = buildBody("evt_01JABCDEF", "order.created", "2026-10-30T12:00:00.000000Z", {
  order_id: "ORD-101",
  customer: "Zoë",
  note: "café ☕",
  total: 12.5,
});

function headersFor({ body = BODY, secrets = [SECRET], ts = NOW } = {}) {
  return {
    "Content-Type": "application/json",
    "HookFlow-Event-Id": "evt_01JABCDEF",
    "HookFlow-Event-Type": "order.created",
    "HookFlow-Delivery-Id": "dlv_01JABCDEF",
    "HookFlow-Attempt": "1",
    "HookFlow-Timestamp": String(ts),
    "HookFlow-Signature": secrets.map((s) => backendSign(s, ts, body)).join(","),
  };
}

function expectReason(reason, fn) {
  assert.throws(fn, (err) => {
    assert.ok(err instanceof WebhookVerificationError, `expected WebhookVerificationError, got ${err}`);
    assert.equal(err.reason, reason);
    return true;
  });
}

test("valid request returns the parsed event", () => {
  const event = verify(BODY, headersFor(), SECRET, { now: NOW });
  assert.equal(event.id, "evt_01JABCDEF");
  assert.equal(event.type, "order.created");
  assert.equal(event.data.note, "café ☕");
});

test("string and Uint8Array payloads", () => {
  assert.equal(verify(BODY.toString("utf8"), headersFor(), SECRET, { now: NOW }).data.customer, "Zoë");
  assert.ok(verify(new Uint8Array(BODY), headersFor(), SECRET, { now: NOW }));
});

test("uses the real clock by default", () => {
  const ts = Math.floor(Date.now() / 1000);
  assert.ok(verify(BODY, headersFor({ ts }), SECRET));
});

test("tampered body", () => {
  const tampered = Buffer.from(BODY.toString().replace("ORD-101", "ORD-999"));
  expectReason("signature_mismatch", () => verify(tampered, headersFor(), SECRET, { now: NOW }));
});

test("re-serialized JSON fails", () => {
  const reserialized = JSON.stringify(JSON.parse(BODY.toString()), null, 1);
  expectReason("signature_mismatch", () => verify(reserialized, headersFor(), SECRET, { now: NOW }));
});

test("wrong secret, and secret without the whsec_ prefix", () => {
  expectReason("signature_mismatch", () => verify(BODY, headersFor(), "whsec_wrong", { now: NOW }));
  expectReason("signature_mismatch", () => verify(BODY, headersFor(), SECRET.slice(6), { now: NOW }));
});

test("tampered timestamp", () => {
  const h = { ...headersFor(), "HookFlow-Timestamp": String(NOW + 1) };
  expectReason("signature_mismatch", () => verify(BODY, h, SECRET, { now: NOW }));
});

test("timestamp outside tolerance", () => {
  for (const offset of [301, -301, 10_000]) {
    expectReason("timestamp_out_of_tolerance", () => verify(BODY, headersFor({ ts: NOW + offset }), SECRET, { now: NOW }));
  }
  for (const offset of [300, -300, 0]) {
    assert.ok(verify(BODY, headersFor({ ts: NOW + offset }), SECRET, { now: NOW }));
  }
});

test("custom tolerance (options object or number)", () => {
  const h = headersFor({ ts: Math.floor(Date.now() / 1000) - 50 });
  expectReason("timestamp_out_of_tolerance", () => verify(BODY, h, SECRET, 10));
  assert.ok(verify(BODY, h, SECRET, 60));
  assert.ok(verify(BODY, h, SECRET, { toleranceSeconds: 60 }));
  assert.ok(verify(BODY, headersFor({ ts: 1 }), SECRET, { toleranceSeconds: null }));
});

test("rotation: two signatures, either secret verifies", () => {
  const h = headersFor({ secrets: [SECRET, OLD_SECRET] });
  assert.equal(h["HookFlow-Signature"].split("v1=").length - 1, 2);
  assert.ok(verify(BODY, h, SECRET, { now: NOW }));
  assert.ok(verify(BODY, h, OLD_SECRET, { now: NOW }));
  expectReason("signature_mismatch", () => verify(BODY, h, "whsec_neither", { now: NOW }));
});

test("signature list with spaces and unknown schemes", () => {
  const h = { ...headersFor(), "HookFlow-Signature": `v0=deadbeef, ${backendSign(SECRET, NOW, BODY)} ,v2=abc` };
  assert.ok(verify(BODY, h, SECRET, { now: NOW }));
});

test("case-insensitive headers in every shape", () => {
  const base = headersFor();
  const lower = Object.fromEntries(Object.entries(base).map(([k, v]) => [k.toLowerCase(), v]));
  const upper = Object.fromEntries(Object.entries(base).map(([k, v]) => [k.toUpperCase(), v]));
  const opts = { now: NOW };
  assert.ok(verify(BODY, lower, SECRET, opts)); // Express / IncomingHttpHeaders
  assert.ok(verify(BODY, upper, SECRET, opts));
  assert.ok(verify(BODY, Object.entries(base), SECRET, opts));
  assert.ok(verify(BODY, new Map(Object.entries(upper)), SECRET, opts));
  assert.ok(verify(BODY, new Headers(base), SECRET, opts)); // Fetch API
  // Node may give string[] for repeated headers
  const arr = { ...lower, "hookflow-signature": [backendSign(SECRET, NOW, BODY)] };
  assert.ok(verify(BODY, arr, SECRET, opts));
});

test("missing headers", () => {
  for (const name of ["HookFlow-Timestamp", "HookFlow-Signature"]) {
    const h = headersFor();
    delete h[name];
    assert.throws(() => verify(BODY, h, SECRET, { now: NOW }), (err) => {
      assert.equal(err.reason, "missing_header");
      assert.match(err.message, new RegExp(name));
      return true;
    });
  }
});

test("invalid timestamps", () => {
  for (const value of ["", "abc", "1793361600.5", "-1793361600", "１２３", "1e9"]) {
    const h = { ...headersFor(), "HookFlow-Timestamp": value };
    expectReason("invalid_timestamp", () => verify(BODY, h, SECRET, { now: NOW }));
  }
});

test("no v1 signatures", () => {
  for (const value of ["", "deadbeef", "v2=abc", "sha256=abc"]) {
    const h = { ...headersFor(), "HookFlow-Signature": value };
    expectReason("no_signatures", () => verify(BODY, h, SECRET, { now: NOW }));
  }
});

test("wrong-length or non-ASCII signature does not crash", () => {
  for (const value of ["v1=abc", "v1=é" + "0".repeat(63)]) {
    const h = { ...headersFor(), "HookFlow-Signature": value };
    expectReason("signature_mismatch", () => verify(BODY, h, SECRET, { now: NOW }));
  }
});

test("payload must be a JSON object", () => {
  for (const body of ["[1,2,3]", "not json", "null"]) {
    expectReason("invalid_payload", () => verify(body, headersFor({ body }), SECRET, { now: NOW }));
  }
});

test("parsed object payload is rejected with a helpful message", () => {
  assert.throws(() => verify({ id: "evt" }, headersFor(), SECRET, { now: NOW }), /raw request body/);
  assert.throws(() => verify(BODY, headersFor(), "", { now: NOW }), TypeError);
});

test("verifySignature does not parse", () => {
  const body = "not json at all";
  assert.equal(verifySignature(body, headersFor({ body }), SECRET, { now: NOW }), undefined);
});

test("sign() matches the backend algorithm", () => {
  assert.equal(sign(SECRET, NOW, BODY), backendSign(SECRET, NOW, BODY));
});

test("known vector computed with backend/app/signing.py", () => {
  // python3 -c "from app.signing import sign; print(sign('whsec_test_secret', 1793361600, body))"
  const body = '{"id":"evt_1","type":"order.created","data":{"name":"café"}}';
  const expected = "v1=0990157a818811453e3242c3407bd799a277532d200d6eda5ba34719ae30650e";
  assert.equal(sign("whsec_test_secret", 1793361600, body), expected);
  const h = { "hookflow-timestamp": "1793361600", "hookflow-signature": expected };
  assert.equal(verify(body, h, "whsec_test_secret", { now: 1793361600 }).data.name, "café");
});

test("cross-check: run backend/app/signing.py itself (if python3 is available)", (t) => {
  if (!hasBackend) return t.skip("backend/app/signing.py not present");
  const script = `
import importlib.util, sys, json
spec = importlib.util.spec_from_file_location("signing", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
body = sys.stdin.buffer.read()
print(json.dumps([m.sign(s, ${NOW}, body) for s in sys.argv[2:]]))
`;
  const run = spawnSync("python3", ["-I", "-c", script, BACKEND_SIGNING, SECRET, OLD_SECRET], { input: BODY });
  if (run.error || run.status !== 0) return t.skip(`python3 unavailable: ${run.error ?? run.stderr}`);
  const [newSig, oldSig] = JSON.parse(run.stdout.toString());
  assert.equal(newSig, backendSign(SECRET, NOW, BODY));
  const h = { ...headersFor(), "HookFlow-Signature": `${newSig},${oldSig}` };
  assert.ok(verify(BODY, h, SECRET, { now: NOW }));
  assert.ok(verify(BODY, h, OLD_SECRET, { now: NOW }));
});

test("cross-check: agrees with the Node snippet in docs/api.md", (t) => {
  if (!hasDocs) return t.skip("docs/api.md not present");
  const section = readFileSync(API_DOCS, "utf8").split("### Verifying the signature")[1];
  const snippet = section.match(/```js\n([\s\S]*?)```/)[1].replace(/^import .*$/m, "");
  const docsVerify = new Function("crypto", "Buffer", "Date", `${snippet}\nreturn verify;`)(
    crypto,
    Buffer,
    { now: () => NOW * 1000 },
  );
  const cases = [
    [BODY, headersFor(), SECRET],
    [BODY, headersFor({ secrets: [SECRET, OLD_SECRET] }), OLD_SECRET],
    [Buffer.from(BODY.toString().replace("101", "102")), headersFor(), SECRET],
    [BODY, headersFor(), "whsec_wrong"],
    [BODY, headersFor({ ts: NOW - 301 }), SECRET],
    [BODY, headersFor({ ts: NOW + 299 }), SECRET],
  ];
  for (const [body, h, secret] of cases) {
    const expected = docsVerify(secret, body, h["HookFlow-Timestamp"], h["HookFlow-Signature"]);
    let ours = true;
    try {
      verify(body, h, secret, { now: NOW });
    } catch (err) {
      assert.ok(err instanceof WebhookVerificationError);
      ours = false;
    }
    assert.equal(ours, expected);
  }
});

test("CommonJS build exposes the same API", () => {
  const require = createRequire(import.meta.url);
  const cjs = require("../dist/cjs/index.js");
  assert.equal(typeof cjs.verify, "function");
  assert.equal(typeof cjs.HookFlow, "function");
  assert.ok(cjs.verify(BODY, headersFor(), SECRET, { now: NOW }));
  assert.throws(() => cjs.verify(BODY, headersFor(), "whsec_x", { now: NOW }), cjs.WebhookVerificationError);
});
