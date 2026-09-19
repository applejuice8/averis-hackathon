import { api, COMPARE_FIELDS } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function EmailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const e = await api.email(id);
  const r = e.result;

  const verdict =
    r?.status === "MISMATCH"
      ? `${r.defect_fields.length} field${r.defect_fields.length > 1 ? "s" : ""} differ`
      : r?.status === "NEEDS_REVIEW"
        ? `Escalated: ${r.review_reason}`
        : r?.status === "OK" && r.category === "BL_COMPARISON"
          ? "No mismatch detected"
          : r?.status === "OK"
            ? "Triaged — no document check needed"
            : "Not processed yet";

  return (
    <>
      <h1>{e.email_id}</h1>
      <h2>{e.subject}</h2>

      <div className="cards">
        <div className="card"><div className="lbl">From</div><div>{e.sender}</div></div>
        <div className="card"><div className="lbl">Queue</div><div>{r?.category ?? "—"} {r?.decided_by && <span className="badge dim">{r.decided_by}</span>}</div></div>
        <div className="card"><div className="lbl">Verdict</div>
          <div style={{ color: r?.status === "MISMATCH" ? "var(--bad)" : r?.status === "NEEDS_REVIEW" ? "var(--warn)" : "var(--ok)" }}>{verdict}</div>
        </div>
      </div>

      {r?.si_fields && r?.bl_fields && (
        <>
          <h2>SI vs draft BL — field comparison</h2>
          <table className="diff">
            <thead><tr><th>Field</th><th>SI (reference)</th><th>Draft BL</th><th></th></tr></thead>
            <tbody>
              {COMPARE_FIELDS.map((f) => {
                const diff = r.defect_fields.includes(f);
                return (
                  <tr key={f}>
                    <td>{f}</td>
                    <td className={diff ? "mismatch" : ""}>{String(r.si_fields?.[f] ?? "—")}</td>
                    <td className={diff ? "mismatch" : ""}>{String(r.bl_fields?.[f] ?? "—")}</td>
                    <td className={diff ? "mismatch" : "match"}>{diff ? "✗ differs" : "✓"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {r?.doc_types && (
        <>
          <h2>Detected document types</h2>
          <pre>{JSON.stringify(r.doc_types, null, 2)}</pre>
        </>
      )}
      {r?.evidence && (
        <>
          <h2>Evidence</h2>
          <pre>{JSON.stringify(r.evidence, null, 2)}</pre>
        </>
      )}
      {r?.error && (<><h2>Error</h2><pre>{r.error}</pre></>)}

      <h2>Original email</h2>
      <pre>{e.body}</pre>
      {e.attachments.length > 0 && <pre>{e.attachments.join("\n")}</pre>}
    </>
  );
}
