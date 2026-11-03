import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

import {
  HookFlow,
  HookFlowError,
  APIConnectionError,
  APITimeoutError,
  BadRequestError,
  AuthenticationError,
  PermissionDeniedError,
  NotFoundError,
  ConflictError,
  PayloadTooLargeError,
  ValidationError,
  RateLimitError,
  InternalServerError,
} from "../dist/esm/index.js";
import { errorBody, startStub } from "./helpers.mjs";

const KEY = "hf_ab12cd34_secretsecret";
const ACCEPTED = { event_id: "evt_1", status: "accepted", created_at: "2026-10-30T12:00:00Z", delivery_count: 2 };

let stub;
let client;
let sleeps;

class TestClient extends HookFlow {
  sleep(ms) {
    sleeps.push(ms);
    return Promise.resolve();
  }
}

beforeEach(async () => {
  stub = await startStub();
  sleeps = [];
  client = new TestClient({ apiKey: KEY, baseUrl: `${stub.baseUrl}/`, timeout: 5000, maxRetries: 2 });
});
afterEach(() => stub.close());

test("requires an API key; reads env vars", () => {
  const saved = { ...process.env };
  try {
    delete process.env.HOOKFLOW_API_KEY;
    assert.throws(() => new HookFlow(), TypeError);
    process.env.HOOKFLOW_API_KEY = "hf_env_key";
    process.env.HOOKFLOW_BASE_URL = "https://hooks.example.com/";
    const c = new HookFlow();
    assert.equal(c.apiKey, "hf_env_key");
    assert.equal(c.baseUrl, "https://hooks.example.com");
  } finally {
    process.env = saved;
  }
});

test("events.send", async () => {
  stub.reply([202, ACCEPTED]);
  assert.deepEqual(await client.events.send("order.created", { order_id: "ORD-1", name: "café" }), ACCEPTED);
  const req = stub.last;
  assert.equal(req.method, "POST");
  assert.equal(req.path, "/v1/events");
  assert.equal(req.headers.authorization, `Bearer ${KEY}`);
  assert.equal(req.headers["content-type"], "application/json");
  assert.match(req.headers["user-agent"], /^hookflow-node\//);
  assert.equal(req.headers["idempotency-key"], undefined);
  assert.deepEqual(req.json, { event_type: "order.created", data: { order_id: "ORD-1", name: "café" } });
});

test("events.send with idempotency key", async () => {
  stub.reply([202, ACCEPTED, { "Idempotent-Replayed": "true" }]);
  await client.events.send("order.created", { a: 1 }, { idempotencyKey: "order-ORD-1-created" });
  assert.equal(stub.last.headers["idempotency-key"], "order-ORD-1-created");
});

test("events.send without a key is never retried", async () => {
  stub.reply([503, errorBody("service_unavailable", "Down"), { "Retry-After": "1" }]);
  await assert.rejects(client.events.send("order.created", {}), (err) => {
    assert.ok(err instanceof InternalServerError);
    assert.equal(err.retryAfter, 1);
    return true;
  });
  assert.equal(stub.requests.length, 1);
  assert.deepEqual(sleeps, []);
});

test("events.send with a key is retried on 429 then 5xx", async () => {
  stub.reply(
    [429, errorBody("rate_limited", "Slow down"), { "Retry-After": "2" }],
    [500, errorBody("internal_error", "Oops")],
    [202, ACCEPTED],
  );
  assert.deepEqual(await client.events.send("order.created", {}, { idempotencyKey: "k1" }), ACCEPTED);
  assert.equal(stub.requests.length, 3);
  assert.ok(stub.requests.every((r) => r.headers["idempotency-key"] === "k1"));
  assert.equal(sleeps[0], 2000); // honours Retry-After
  assert.equal(sleeps.length, 2);
});

test("retries exhausted; non-JSON error body", async () => {
  stub.handler = () => [502, "Bad Gateway"];
  await assert.rejects(client.events.get("evt_1"), (err) => {
    assert.ok(err instanceof InternalServerError);
    assert.equal(err.status, 502);
    assert.equal(err.message, "Bad Gateway");
    assert.equal(err.code, null);
    return true;
  });
  assert.equal(stub.requests.length, 3);
});

test("a long Retry-After is not waited for", async () => {
  stub.reply([429, errorBody("quota_exceeded", "Daily quota"), { "Retry-After": "40000" }]);
  await assert.rejects(client.events.list(), (err) => {
    assert.ok(err instanceof RateLimitError);
    assert.equal(err.retryAfter, 40000);
    assert.equal(err.code, "quota_exceeded");
    return true;
  });
  assert.equal(stub.requests.length, 1);
  assert.deepEqual(sleeps, []);
});

test("maxRetries: 0 disables retries", async () => {
  const c = new TestClient({ apiKey: KEY, baseUrl: stub.baseUrl, maxRetries: 0 });
  stub.reply([503, errorBody("service_unavailable", "Down")]);
  await assert.rejects(c.deliveries.get("dlv_1"), InternalServerError);
  assert.equal(stub.requests.length, 1);
});

test("other POST and PATCH requests are not retried", async () => {
  stub.handler = () => [500, errorBody("internal_error", "x")];
  await assert.rejects(client.deliveries.replay("dlv_1"), InternalServerError);
  await assert.rejects(client.endpoints.update("ep_1", { enabled: false }), InternalServerError);
  await assert.rejects(client.deliveries.bulkReplay({ dry_run: false }), InternalServerError);
  assert.equal(stub.requests.length, 3);
});

test("error mapping by status", async () => {
  const details = [{ loc: ["body", "event_type"], msg: "bad", type: "value_error" }];
  const cases = [
    [400, "bad_request", BadRequestError],
    [401, "unauthorized", AuthenticationError],
    [403, "forbidden", PermissionDeniedError],
    [404, "not_found", NotFoundError],
    [409, "idempotency_key_reused", ConflictError],
    [413, "payload_too_large", PayloadTooLargeError],
    [422, "validation_error", ValidationError],
    [429, "rate_limited", RateLimitError],
    [418, "error", HookFlowError],
  ];
  for (const [status, code, Cls] of cases) {
    stub.reply([status, errorBody(code, "Something failed.", details), { "Retry-After": "0" }]);
    await assert.rejects(client.events.send("order.created", {}), (err) => {
      assert.ok(err instanceof Cls, `${status} -> ${err.name}`);
      assert.ok(err instanceof HookFlowError);
      assert.deepEqual([err.status, err.code, err.message, err.details], [status, code, "Something failed.", details]);
      return true;
    });
  }
  assert.ok(new PermissionDeniedError("x") instanceof AuthenticationError);
});

test("connection error", async () => {
  const c = new HookFlow({ apiKey: KEY, baseUrl: "http://127.0.0.1:9", maxRetries: 0 });
  await assert.rejects(c.events.get("evt_1"), (err) => {
    assert.ok(err instanceof APIConnectionError);
    assert.equal(err.status, null);
    return true;
  });
});

test("timeout", async () => {
  stub.delayMs = 500;
  const c = new HookFlow({ apiKey: KEY, baseUrl: stub.baseUrl, timeout: 50, maxRetries: 0 });
  await assert.rejects(c.events.get("evt_1"), APITimeoutError);
});

test("events.list query params and auto-pagination", async () => {
  const pages = {
    "": { data: [{ id: "evt_3" }, { id: "evt_2" }], next_cursor: "evt_2" },
    evt_2: { data: [{ id: "evt_1" }], next_cursor: null },
  };
  stub.handler = (req) => [200, pages[req.query.cursor?.[0] ?? ""]];
  const page = await client.events.list({
    event_type: "order.created",
    created_after: new Date("2026-10-01T00:00:00Z"),
    limit: 2,
  });
  assert.deepEqual(page.data.map((e) => e.id), ["evt_3", "evt_2"]);
  assert.equal(page.hasMore, true);
  assert.equal(page.nextCursor, "evt_2");
  assert.deepEqual(stub.requests[0].query, {
    event_type: ["order.created"],
    created_after: ["2026-10-01T00:00:00.000Z"],
    limit: ["2"],
  });

  const ids = [];
  for await (const e of client.events.listAll({ event_type: "order.created", limit: 2 })) ids.push(e.id);
  assert.deepEqual(ids, ["evt_3", "evt_2", "evt_1"]);
  assert.deepEqual(stub.last.query, { event_type: ["order.created"], limit: ["2"], cursor: ["evt_2"] });

  const viaPage = [];
  for await (const e of page) viaPage.push(e.id);
  assert.deepEqual(viaPage, ["evt_3", "evt_2", "evt_1"]);
  const next = await page.getNextPage();
  assert.equal(next.hasMore, false);
  assert.equal(await next.getNextPage(), null);
});

test("auto-pagination is lazy", async () => {
  stub.handler = () => [200, { data: [{ id: "x" }], next_cursor: "more" }];
  const it = client.deliveries.listAll({ status: "failed" });
  assert.equal((await it.next()).value.id, "x");
  assert.equal(stub.requests.length, 1);
  await it.next();
  assert.equal(stub.requests.length, 2);
  await it.return();
});

test("events.get / deliveries / replay", async () => {
  stub.handler = (req) => [
    req.method === "POST" ? 202 : 200,
    req.path.endsWith("/deliveries") ? { data: [{ id: "dlv_1" }] } : req.method === "POST" ? { replayed: [], skipped: [] } : { id: "evt_1" },
  ];
  assert.deepEqual(await client.events.get("evt_1"), { id: "evt_1" });
  assert.equal(stub.last.path, "/v1/events/evt_1");
  assert.deepEqual(await client.events.deliveries("evt_1"), [{ id: "dlv_1" }]);
  assert.equal(stub.last.path, "/v1/events/evt_1/deliveries");
  await client.events.replay("evt_1");
  assert.equal(stub.last.path, "/v1/events/evt_1/replay");
  assert.deepEqual(stub.last.json, {});
  await client.events.replay("evt_1", ["ep_1", "ep_2"]);
  assert.deepEqual(stub.last.json, { endpoint_ids: ["ep_1", "ep_2"] });
});

test("nothing_to_replay exposes details", async () => {
  const skipped = [{ delivery_id: "dlv_1", reason: "Delivery is delivered." }];
  stub.reply([409, errorBody("nothing_to_replay", "None can be replayed.", skipped)]);
  await assert.rejects(client.events.replay("evt_1"), (err) => {
    assert.ok(err instanceof ConflictError);
    assert.equal(err.code, "nothing_to_replay");
    assert.deepEqual(err.details, skipped);
    return true;
  });
});

test("deliveries resource", async () => {
  stub.handler = (req) => [req.method === "POST" ? 202 : 200, { data: [{ attempt_number: 1 }], next_cursor: null }];
  assert.deepEqual(await client.deliveries.attempts("dlv_1"), [{ attempt_number: 1 }]);
  assert.equal(stub.last.path, "/v1/deliveries/dlv_1/attempts");
  await client.deliveries.replays("dlv_1");
  assert.equal(stub.last.path, "/v1/deliveries/dlv_1/replays");
  await client.deliveries.get("dlv_1");
  assert.equal(stub.last.path, "/v1/deliveries/dlv_1");
  await client.deliveries.replay("dlv_1");
  assert.deepEqual([stub.last.method, stub.last.path], ["POST", "/v1/deliveries/dlv_1/replay"]);
  await client.deliveries.list({ status: "failed", endpoint_id: "ep_1", event_id: "evt_1", limit: 10, cursor: "dlv_9" });
  assert.deepEqual(stub.last.query, {
    status: ["failed"], endpoint_id: ["ep_1"], event_id: ["evt_1"], limit: ["10"], cursor: ["dlv_9"],
  });
});

test("ids are path-escaped", async () => {
  stub.handler = () => [200, {}];
  await client.deliveries.get("../endpoints/x");
  assert.equal(stub.last.path, "/v1/deliveries/..%2Fendpoints%2Fx");
  assert.throws(() => client.deliveries.get(""), TypeError);
});

test("deliveries.bulkReplay", async () => {
  const result = { matched: 3, replayed: ["dlv_1", "dlv_2"], skipped: [{ delivery_id: "dlv_3", reason: "x" }], has_more: false, dry_run: false };
  stub.handler = () => [202, result];
  assert.deepEqual(await client.deliveries.bulkReplay(), result);
  assert.deepEqual([stub.last.method, stub.last.path, stub.last.json], ["POST", "/v1/deliveries/replay", {}]);

  await client.deliveries.bulkReplay({
    endpoint_id: "ep_1",
    event_type: "order.created",
    statuses: ["failed", "cancelled"],
    created_after: new Date("2026-10-01T00:00:00Z"),
    created_before: "2026-10-02T00:00:00Z",
    limit: 500,
    dry_run: true,
  });
  assert.deepEqual(stub.last.json, {
    endpoint_id: "ep_1",
    event_type: "order.created",
    statuses: ["failed", "cancelled"],
    created_after: "2026-10-01T00:00:00.000Z",
    created_before: "2026-10-02T00:00:00Z",
    limit: 500,
    dry_run: true,
  });
});

test("endpoints CRUD", async () => {
  const ep = { id: "ep_1", url: "https://example.com/hooks", event_types: ["*"] };
  stub.handler = (req) => {
    if (req.method === "DELETE") return [204, null];
    if (req.method === "POST") return [201, { ...ep, signing_secret: "whsec_abc" }];
    if (req.path === "/v1/endpoints") return [200, { data: [ep], next_cursor: null }];
    return [200, ep];
  };
  const created = await client.endpoints.create({ url: ep.url, event_types: ["*"], description: "Main", max_attempts: 3 });
  assert.equal(created.signing_secret, "whsec_abc");
  assert.deepEqual(stub.last.json, { url: ep.url, event_types: ["*"], description: "Main", max_attempts: 3 });

  assert.deepEqual((await client.endpoints.list()).data, [ep]);
  const all = [];
  for await (const e of client.endpoints.listAll()) all.push(e.id);
  assert.deepEqual(all, ["ep_1"]);
  assert.deepEqual(await client.endpoints.get("ep_1"), ep);

  await client.endpoints.update("ep_1", { enabled: false, description: null, url: undefined });
  assert.deepEqual([stub.last.method, stub.last.path], ["PATCH", "/v1/endpoints/ep_1"]);
  assert.deepEqual(stub.last.json, { enabled: false, description: null });

  assert.equal(await client.endpoints.delete("ep_1"), undefined);
  assert.deepEqual([stub.last.method, stub.last.path], ["DELETE", "/v1/endpoints/ep_1"]);

  await client.endpoints.secret("ep_1");
  assert.equal(stub.last.path, "/v1/endpoints/ep_1/secret");
  await client.endpoints.rotateSecret("ep_1", 0);
  assert.equal(stub.last.path, "/v1/endpoints/ep_1/rotate-secret");
  assert.deepEqual(stub.last.json, { grace_period_seconds: 0 });
});

test("package self-reference resolves both ESM and CJS entry points", async () => {
  const esm = await import("hookflow");
  const cjs = createRequire(import.meta.url)("hookflow");
  assert.equal(typeof esm.HookFlow, "function");
  assert.equal(typeof cjs.HookFlow, "function");
  assert.equal(typeof cjs.verify, "function");
});

test("endpoint retry_schedule passthrough", async () => {
  stub.handler = (req) => [req.method === "POST" ? 201 : 200, { id: "ep_1" }];
  await client.endpoints.create({ url: "https://example.com/h", event_types: ["order.created"], retry_schedule: [10, 60] });
  assert.deepEqual(stub.last.json.retry_schedule, [10, 60]);
  await client.endpoints.update("ep_1", { retry_schedule: null });
  assert.deepEqual(stub.last.json, { retry_schedule: null });
});

test("insufficient_scope (403) is a PermissionDeniedError", async () => {
  stub.reply([403, errorBody("insufficient_scope", "This API key doesn't have the 'deliveries:replay' scope.", { required_scope: "deliveries:replay" })]);
  await assert.rejects(client.deliveries.bulkReplay(), (err) => {
    assert.ok(err instanceof PermissionDeniedError && err instanceof AuthenticationError);
    assert.deepEqual(err.details, { required_scope: "deliveries:replay" });
    return true;
  });
});
