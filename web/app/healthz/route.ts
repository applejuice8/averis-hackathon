// Process liveness only: never wakes Neon or calls a model.
export function GET() {
  return Response.json({ ok: true }, { headers: { "cache-control": "no-store" } });
}
