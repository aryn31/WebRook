// Test helpers: a node:http stub standing in for the HookFlow API, and a port of the backend signer.
import { createHmac } from "node:crypto";
import { createServer } from "node:http";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
export const BACKEND_SIGNING = path.join(REPO_ROOT, "backend/app/signing.py");
export const API_DOCS = path.join(REPO_ROOT, "docs/api.md");
export const hasBackend = existsSync(BACKEND_SIGNING);
export const hasDocs = existsSync(API_DOCS);

/** Port of backend/app/signing.py::sign: v1=hex(HMAC-SHA256(secret.encode(), f"{ts}.".encode() + body)). */
export function backendSign(secret, timestamp, body) {
  const mac = createHmac("sha256", Buffer.from(secret, "utf8"));
  mac.update(Buffer.from(`${timestamp}.`, "utf8"));
  mac.update(Buffer.isBuffer(body) ? body : Buffer.from(body, "utf8"));
  return `v1=${mac.digest("hex")}`;
}

/** Port of backend/app/worker/engine.py::build_body (compact separators, ensure_ascii=False, UTF-8). */
export function buildBody(id, type, createdAt, data) {
  return Buffer.from(JSON.stringify({ id, type, created_at: createdAt, data }), "utf8");
}

export function errorBody(code, message, details = null) {
  return { error: { code, message, details } };
}

/**
 * Start a stub API server. Each reply is [status, body, headers?]; body may be an object (JSON), a string
 * (sent as-is) or null (empty).
 */
export async function startStub() {
  const state = {
    requests: [],
    queue: [],
    handler: () => [200, {}],
    delayMs: 0,
    reply(...replies) {
      state.queue.push(...replies);
    },
    get last() {
      return state.requests.at(-1);
    },
  };
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const url = new URL(req.url, "http://stub");
      const raw = Buffer.concat(chunks);
      const rec = {
        method: req.method,
        path: url.pathname,
        query: Object.fromEntries([...url.searchParams.keys()].map((k) => [k, url.searchParams.getAll(k)])),
        headers: req.headers,
        body: raw,
        json: raw.length ? JSON.parse(raw.toString("utf8")) : undefined,
      };
      state.requests.push(rec);
      const [status, body, headers = {}] = state.queue.length ? state.queue.shift() : state.handler(rec);
      const send = () => {
        const payload = body == null ? "" : typeof body === "string" ? body : JSON.stringify(body);
        const h = { ...headers, "Content-Length": Buffer.byteLength(payload) };
        if (body != null && typeof body !== "string") h["Content-Type"] = "application/json";
        res.writeHead(status, h);
        res.end(payload);
      };
      state.delayMs ? setTimeout(send, state.delayMs) : send();
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  state.baseUrl = `http://127.0.0.1:${server.address().port}`;
  state.close = () =>
    new Promise((resolve) => {
      server.closeAllConnections?.();
      server.close(resolve);
    });
  return state;
}
