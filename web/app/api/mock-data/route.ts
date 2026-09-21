import { NextRequest, NextResponse } from "next/server";
import { DATA_LOADED_COOKIE, sameOrigin } from "@/lib/server";

export const dynamic = "force-dynamic";

function cookieOptions(request: NextRequest) {
  return {
    httpOnly: true,
    secure: Boolean(process.env.VERCEL) || request.nextUrl.protocol === "https:",
    sameSite: "lax" as const,
    path: "/",
  };
}

export function POST(request: NextRequest) {
  if (!sameOrigin(request)) return Response.json({ detail: "A same-origin request is required." }, { status: 403 });
  const response = NextResponse.json({ loaded: true }, { headers: { "cache-control": "no-store" } });
  response.cookies.set(DATA_LOADED_COOKIE, "1", cookieOptions(request));
  return response;
}

export function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return Response.json({ detail: "A same-origin request is required." }, { status: 403 });
  const response = NextResponse.json({ loaded: false }, { headers: { "cache-control": "no-store" } });
  response.cookies.set(DATA_LOADED_COOKIE, "", { ...cookieOptions(request), maxAge: 0 });
  return response;
}
