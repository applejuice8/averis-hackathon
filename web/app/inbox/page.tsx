import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

function badge(status: string | null, hasDefect: boolean | null) {
  if (!status) return <span className="badge dim">unprocessed</span>;
  if (status === "MISMATCH") return <span className="badge bad">MISMATCH</span>;
  if (status === "NEEDS_REVIEW") return <span className="badge warn">NEEDS REVIEW</span>;
  if (status === "FAILED") return <span className="badge bad">FAILED</span>;
  return <span className="badge ok">OK</span>;
}

export default async function Inbox({
  searchParams,
}: {
  searchParams: Promise<{ queue?: string; status?: string }>;
}) {
  const { queue, status } = await searchParams;
  const emails = await api.emails();
  const filtered = emails.filter(
    (e) => (!queue || e.category === queue) && (!status || e.status === status)
  );

  return (
    <>
      <h1>Inbox</h1>
      <div className="filters">
        <form id="f">
          <select name="queue" defaultValue={queue ?? ""}>
            <option value="">all queues</option>
            {["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"].map((q) => (
              <option key={q} value={q}>{q}</option>
            ))}
          </select>{" "}
          <select name="status" defaultValue={status ?? ""}>
            <option value="">all verdicts</option>
            {["OK", "MISMATCH", "NEEDS_REVIEW", "FAILED"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>{" "}
          <button type="submit">Filter</button>
        </form>
      </div>
      <table>
        <thead>
          <tr>
            <th>Email</th><th>From</th><th>Subject</th><th>Queue</th><th>Verdict</th><th>How</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((e) => (
            <tr key={e.email_id}>
              <td><Link href={`/emails/${e.email_id}`}>{e.email_id}</Link></td>
              <td>{e.sender}</td>
              <td style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.subject}</td>
              <td>{e.category && <span className="badge info">{e.category}</span>}</td>
              <td>{badge(e.status, e.has_defect)}
                {e.defect_fields?.length ? <span style={{ color: "var(--bad)" }}> {e.defect_fields.join(", ")}</span> : null}
                {e.review_reason ? <span style={{ color: "var(--warn)" }}> {e.review_reason}</span> : null}
              </td>
              <td>{e.decided_by && <span className="badge dim">{e.decided_by}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
