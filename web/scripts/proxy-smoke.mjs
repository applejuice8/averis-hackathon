// Run after `pnpm build`. Exercises a real production Next server against a local stub.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
let calls = 0;
const stub = createServer(async (req, res) => {
  calls++;
  if (req.url === "/api/auth/check") {
    res.writeHead(req.headers["x-demo-passcode"] === "demo-test-only" ? 204 : 401);
    return res.end();
  }
  if (req.url === "/api/oversize") return res.end("x".repeat(4_000_001));
  if (req.url === "/api/empty") { res.writeHead(204); return res.end(); }
  const parts = [];
  for await (const chunk of req) parts.push(chunk);
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify({ method: req.method, url: req.url, passcode: req.headers["x-demo-passcode"] ?? null,
    cookie: req.headers.cookie ?? null, body: Buffer.concat(parts).toString() }));
});
stub.listen(0, "127.0.0.1");
await once(stub, "listening");
const probe = createServer();
probe.listen(0, "127.0.0.1");
await once(probe, "listening");
const port = probe.address().port;
await new Promise(resolve => probe.close(resolve));
const origin = `http://127.0.0.1:${port}`;
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", String(port)], {
  cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, VERCEL: "", API_URL: `http://127.0.0.1:${stub.address().port}`, NEXT_TELEMETRY_DISABLED: "1" },
});
let output = "";
child.stdout.on("data", chunk => { output += chunk; });
child.stderr.on("data", chunk => { output += chunk; });
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error(output);
    try { ready = (await fetch(`${origin}/healthz`)).ok; } catch { /* starting */ }
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(ready, "production server starts");
  assert.equal(calls, 0, "liveness never calls backend");
  let result = await fetch(`${origin}/api/echo?q=one%20two`, { headers: { "x-demo-passcode": "forged", cookie: "unrelated=private" } });
  const echo = await result.json();
  assert.equal(new URL(echo.url, origin).searchParams.get("q"), "one two");
  assert.deepEqual({ ...echo, url: "/api/echo" }, { method: "GET", url: "/api/echo", passcode: null, cookie: null, body: "" });
  assert.equal(result.headers.get("cache-control"), "no-store");
  for (const badOrigin of [undefined, "https://untrusted.example"]) {
    const headers = badOrigin ? { origin: badOrigin } : {};
    assert.equal((await fetch(`${origin}/api/echo`, { method: "POST", headers, body: "test" })).status, 403);
  }
  const login = passcode => fetch(`${origin}/auth/reviewer`, { method: "POST",
    headers: { origin, "content-type": "application/json" }, body: JSON.stringify({ passcode }) });
  assert.equal((await login("incorrect")).status, 401);
  assert.equal((await login("bad\r\nheader")).status, 400);
  result = await login("demo-test-only");
  assert.equal(result.status, 200);
  const setCookie = result.headers.get("set-cookie");
  assert.match(setCookie, /HttpOnly/i);
  assert.match(setCookie, /SameSite=lax/i);
  const cookie = setCookie.split(";")[0];
  result = await fetch(`${origin}/api/echo`, { method: "POST", headers: {
    origin, cookie, "content-type": "application/json", "x-demo-passcode": "forged",
  }, body: '{"action":"review"}' });
  assert.deepEqual(await result.json(), { method: "POST", url: "/api/echo", passcode: "demo-test-only",
    cookie: null, body: '{"action":"review"}' });
  assert.equal((await fetch(`${origin}/api/empty`)).status, 204);
  assert.equal((await fetch(`${origin}/api/echo`, { method: "HEAD" })).status, 200);
  const before = calls;
  assert.equal((await fetch(`${origin}/api/echo`, { method: "POST", headers: { origin }, body: "x".repeat(4_000_001) })).status, 413);
  assert.equal(calls, before, "oversized input never reaches API");
  assert.equal((await fetch(`${origin}/api/oversize`)).status, 413);
  result = await fetch(`${origin}/auth/reviewer`, { method: "DELETE", headers: { origin, cookie } });
  assert.match(result.headers.get("set-cookie"), /Max-Age=0/i);
  stub.closeAllConnections();
  await new Promise(resolve => stub.close(resolve));
  assert.equal((await fetch(`${origin}/api/echo`)).status, 502);
  console.log("PASS: runtime API_URL, liveness, headers, origin checks, reviewer cookie, JSON/HEAD/204, size limits and API outage.");
} finally {
  if (child.exitCode === null) {
    const closed = once(child, "close");
    child.kill();
    await closed;
  }
  stub.closeAllConnections();
  if (stub.listening) await new Promise(resolve => stub.close(resolve));
}
