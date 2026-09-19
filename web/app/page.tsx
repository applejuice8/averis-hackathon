import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

const QUEUES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"];

export default async function Dashboard() {
  const [emails, runs, review] = await Promise.all([api.emails(), api.runs(), api.review()]);
  const latest = runs[0];
  const scored = emails.filter((e) => e.category);

  const byQueue = Object.fromEntries(QUEUES.map((q) => [q, 0]));
  for (const e of scored) byQueue[e.category!] = (byQueue[e.category!] ?? 0) + 1;

  const verdicts = { OK: 0, MISMATCH: 0, NEEDS_REVIEW: 0, FAILED: 0 };
  for (const e of scored) if (e.status) verdicts[e.status as keyof typeof verdicts]++;

  const fs = latest?.score?.final_score as number | undefined;
  const e2e = latest?.score?.end_to_end as { rate?: number } | undefined;

  return (
    <>
      <h1>This morning&apos;s inbox, triaged</h1>
      <h2>
        {scored.length}/{emails.length} emails processed · latest run{" "}
        {latest ? latest.id.slice(0, 8) : "—"}
        {fs !== undefined && <> · score {(fs * 100).toFixed(1)}%</>}
        {e2e?.rate !== undefined && <> · defects caught {(e2e.rate * 100).toFixed(0)}%</>}
      </h2>

      <div className="cards">
        {QUEUES.map((q) => (
          <div className="card" key={q}>
            <div className="num">{byQueue[q]}</div>
            <div className="lbl">{q}</div>
          </div>
        ))}
      </div>

      <div className="cards">
        <div className="card"><div className="num" style={{ color: "var(--ok)" }}>{verdicts.OK}</div><div className="lbl">No mismatch</div></div>
        <div className="card"><div className="num" style={{ color: "var(--bad)" }}>{verdicts.MISMATCH}</div><div className="lbl">Mismatches</div></div>
        <div className="card"><div className="num" style={{ color: "var(--warn)" }}>{verdicts.NEEDS_REVIEW}</div><div className="lbl">Needs review</div></div>
        <div className="card"><div className="num">{review.length}</div><div className="lbl">Review queue</div></div>
      </div>
    </>
  );
}
