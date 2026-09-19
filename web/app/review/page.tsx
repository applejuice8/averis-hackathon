import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const items = await api.review();
  return (
    <>
      <h1>Human review queue</h1>
      <h2>{items.length} cases the pipeline could not decide safely</h2>
      <table>
        <thead>
          <tr><th>Email</th><th>Status</th><th>Reason</th><th>Evidence</th><th></th></tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.result_id}>
              <td><Link href={`/emails/${r.email_id}`}>{r.email_id}</Link></td>
              <td><span className={`badge ${r.status === "FAILED" ? "bad" : "warn"}`}>{r.status}</span></td>
              <td>{r.review_reason ?? "—"}</td>
              <td style={{ maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.error ?? JSON.stringify(r.evidence ?? {})}
              </td>
              <td><Link className="btn" href={`/emails/${r.email_id}`}>Inspect</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
