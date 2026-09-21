import Link from "next/link";
import { api } from "@/lib/api";
import { REASONS } from "@/lib/labels";
import RetryButton from "../components/RetryButton";
import StatusBadge from "../components/StatusBadge";
export const dynamic = "force-dynamic";
export default async function ReviewPage() {
  const items = await api.review();
  return <><div className="page-heading"><div><div className="eyebrow">Human oversight</div><h1>A second look, where it matters.</h1><p>{items.length} cases need a decision before moving forward.</p></div><Link className="btn ghost" href="/inbox?status=MISMATCH">View mismatches →</Link></div><div className="table-wrap"><table><thead><tr><th>Email</th><th>Status</th><th>Why it needs attention</th><th>Next step</th></tr></thead><tbody>{items.map(r => <tr key={r.result_id}><td className="mono"><Link href={`/emails/${r.email_id}`}>{r.email_id}</Link></td><td><StatusBadge status={r.status}/></td><td>{REASONS[r.review_reason ?? ""] ?? r.review_reason ?? "Processing error"}<small>{r.error}</small></td><td><div className="actions"><Link className="text-link" href={`/emails/${r.email_id}`}>Inspect documents →</Link>{r.status === "FAILED" && <RetryButton emailId={r.email_id}/>}</div></td></tr>)}</tbody></table>{!items.length && <div className="empty"><strong>The review queue is clear</strong>Cases that need human judgment will appear here.</div>}</div></>;
}
