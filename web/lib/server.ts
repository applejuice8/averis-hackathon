import "server-only";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

export const DATA_LOADED_COOKIE = "sdoc_data_loaded";
export const REVIEWER_COOKIE = "sdoc_reviewer";
// Below Vercel's 4.5 MB request/response ceiling, including multipart overhead.
export const MAX_PROXY_BYTES = 4_000_000;

export function apiBase(): string {
  const configured = process.env.API_URL || (process.env.VERCEL ? "" : "http://localhost:8000");
  if (!configured) throw new Error("API_URL is required on Vercel.");
  const url = new URL(configured);
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("API_URL must be an origin without credentials or a path.");
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && !process.env.VERCEL)) {
    throw new Error("API_URL must use HTTPS on Vercel.");
  }
  return url.origin;
}

export async function dataLoaded(): Promise<boolean> {
  return (await cookies()).get(DATA_LOADED_COOKIE)?.value === "1";
}

export function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  // Next can normalize the request URL to localhost behind its internal server.
  // The browser's Host header retains the external authority it actually used.
  const host = request.headers.get("host");
  const protocol = process.env.VERCEL ? "https:" : request.nextUrl.protocol;
  return Boolean(host) && origin === `${protocol}//${host}`;
}

export class BodyTooLarge extends Error {}

export async function boundedBody(stream: ReadableStream<Uint8Array> | null, limit = MAX_PROXY_BYTES): Promise<ArrayBuffer> {
  if (!stream) return new ArrayBuffer(0);
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new BodyTooLarge("The request or response exceeds the demo's 4 MB limit.");
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return body.buffer;
}

/** Whether this caller may write: mirrors the API's `require_reviewer` gate. 204 = allowed, anything else = locked. */
export async function reviewerUnlocked(passcode: string | undefined): Promise<boolean> {
  try {
    const r = await fetch(`${apiBase()}/api/auth/check`, {
      headers: passcode ? { "x-demo-passcode": passcode } : {},
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    return r.status === 204;
  } catch {
    return false;
  }
}

export function gatewayError(error: unknown): Response {
  const timeout = error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name);
  const status = error instanceof BodyTooLarge ? 413 : timeout ? 504 : 502;
  const detail = status === 413 ? "This demo supports requests and responses up to 4 MB. Use smaller files."
    : timeout ? "Processing timed out. Check the result before retrying."
      : "The API is unavailable. Please try again later.";
  return Response.json({ detail }, { status, headers: { "cache-control": "no-store" } });
}
