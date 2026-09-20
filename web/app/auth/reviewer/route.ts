import { NextRequest, NextResponse } from "next/server";
import { apiBase, boundedBody, gatewayError, REVIEWER_COOKIE, sameOrigin } from "@/lib/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30;

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return Response.json({ detail: "A same-origin request is required." }, { status: 403 });
  try {
    let passcode: unknown;
    try { ({ passcode } = JSON.parse(new TextDecoder().decode(await boundedBody(request.body, 2048)))); }
    catch { return Response.json({ detail: "Enter a valid passcode." }, { status: 400 }); }
    if (typeof passcode !== "string" || !/^[\x21-\x7e]{1,256}$/.test(passcode)) {
      return Response.json({ detail: "Enter a valid passcode." }, { status: 400 });
    }
    const check = await fetch(`${apiBase()}/api/auth/check`, {
      headers: { "x-demo-passcode": passcode }, cache: "no-store", redirect: "manual",
      signal: AbortSignal.timeout(20_000),
    });
    if (check.status !== 204) {
      return Response.json({ detail: check.status === 401 ? "Incorrect passcode." : "Reviewer access is unavailable." },
        { status: check.status === 401 ? 401 : 502 });
    }
    const response = NextResponse.json({ unlocked: true }, { headers: { "cache-control": "no-store" } });
    response.cookies.set(REVIEWER_COOKIE, passcode, {
      httpOnly: true, secure: Boolean(process.env.VERCEL) || request.nextUrl.protocol === "https:", sameSite: "lax", path: "/", maxAge: 12 * 60 * 60,
    });
    return response;
  } catch (error) { return gatewayError(error); }
}

export function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return Response.json({ detail: "A same-origin request is required." }, { status: 403 });
  const response = NextResponse.json({ unlocked: false }, { headers: { "cache-control": "no-store" } });
  response.cookies.set(REVIEWER_COOKIE, "", { httpOnly: true, secure: Boolean(process.env.VERCEL) || request.nextUrl.protocol === "https:",
    sameSite: "lax", path: "/", maxAge: 0 });
  return response;
}
