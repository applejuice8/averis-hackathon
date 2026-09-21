import type { NextRequest } from "next/server";
import { apiBase, boundedBody, DATA_LOADED_COOKIE, gatewayError, REVIEWER_COOKIE, sameOrigin } from "@/lib/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 120;

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const writes = !["GET", "HEAD"].includes(request.method);
  if (writes && !sameOrigin(request)) {
    return Response.json({ detail: "A same-origin request is required." }, { status: 403 });
  }
  const { path } = await context.params;
  if (path.some(segment => segment === "." || segment === ".." || /[/\\\x00-\x1f]/.test(segment))) {
    return Response.json({ detail: "Invalid API path." }, { status: 400 });
  }
  try {
    const headers = new Headers();
    for (const name of ["content-type", "accept"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    // Never trust a browser-supplied passcode header or forward its cookies.
    const passcode = request.cookies.get(REVIEWER_COOKIE)?.value;
    if (passcode) headers.set("x-demo-passcode", passcode);
    const body = writes ? await boundedBody(request.body) : undefined;
    const upstream = await fetch(`${apiBase()}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "manual",
      signal: AbortSignal.timeout(110_000),
    });
    const out = new Headers({ "cache-control": "no-store" });
    for (const name of ["content-type", "content-disposition"]) {
      const value = upstream.headers.get(name);
      if (value) out.set(name, value);
    }
    const loadedData = request.method === "POST" && path.join("/") === "gmail/sync";
    if (upstream.ok && loadedData) {
      const secure = Boolean(process.env.VERCEL) || request.nextUrl.protocol === "https:";
      out.append("set-cookie", `${DATA_LOADED_COOKIE}=1; Path=/; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`);
    }
    const empty = request.method === "HEAD" || [204, 205, 304].includes(upstream.status);
    return new Response(empty ? null : await boundedBody(upstream.body), { status: upstream.status, headers: out });
  } catch (error) { return gatewayError(error); }
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
