import Link from "next/link";
import { api } from "@/lib/api";
import { QUEUES, STATUS, REASONS, FIELDS } from "@/lib/labels";
import StatusBadge from "../components/StatusBadge";
import GmailControls from "./GmailControls";
export const dynamic = "force-dynamic";
export default async function Inbox({ searchParams }: { searchParams: Promise<{ queue?: string; status?: string; q?: string }> }) {
  const { queue, status, q } = await searchParams;
  const [emails, accounts] = await Promise.all([api.emails(q), api.gmailAccounts().catch(() => [])]);
  const filtered = emails.filter(e => (!queue || e.category === queue) && (!status || e.status === status));
  return <><div className="page-heading"><div><div className="eyebrow">Correspondence</div><h1>Your shipping inbox</h1><p>Find the message. Inspect the evidence. Make the next call.</p></div><div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:8}}><span className="badge dim">{filtered.length} messages</span><GmailControls accounts={accounts}/></div></div>
    <form className="filters"><input aria-label="Search messages" name="q" defaultValue={q} placeholder="Search subject, sender, or email ID…"/><select aria-label="Queue" name="queue" defaultValue={queue ?? ""}><option value="">All queues</option>{Object.entries(QUEUES).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><select aria-label="Verdict" name="status" defaultValue={status ?? ""}><option value="">All verdicts</option>{Object.entries(STATUS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><button type="submit">Apply filters</button>{(q || queue || status) && <Link className="text-link" href="/inbox">Reset</Link>}</form>
    <div className="table-wrap"><table><thead><tr><th>Message</th><th>Queue</th><th>Finding</th><th>Source</th></tr></thead><tbody>{filtered.map(e => <tr key={e.email_id}><td className="subject"><Link href={`/emails/${e.email_id}`}>{e.subject || "Untitled message"}</Link><small>{e.sender}</small><small className="mono">{e.email_id} · {e.n_attachments} attachments</small></td><td>{e.category ? QUEUES[e.category] ?? e.category : "—"}</td><td><StatusBadge status={e.status}/><small>{e.review_reason ? REASONS[e.review_reason] ?? e.review_reason : e.defect_fields?.map(f => FIELDS[f] ?? f).join(", ")}</small></td><td><span className="badge dim">{e.decided_by === "llm" ? "Model" : e.decided_by === "rule" ? "Rules" : "—"}</span></td></tr>)}</tbody></table>{!filtered.length && <div className="empty"><strong>No messages found</strong>Try another search or clear the filters.</div>}</div></>;
}
