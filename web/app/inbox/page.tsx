import Link from "next/link";
import { api } from "@/lib/api";
import { QUEUES, STATUS, REASONS, FIELDS } from "@/lib/labels";
import { dataLoaded } from "@/lib/server";
import StatusBadge from "../components/StatusBadge";
import GmailControls from "./GmailControls";
export const dynamic = "force-dynamic";
const PAGE_SIZE = 10;

function pageHref(p: number, q?: string, queue?: string, status?: string) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (queue) params.set("queue", queue);
  if (status) params.set("status", status);
  if (p > 1) params.set("page", String(p));
  const s = params.toString();
  return s ? `/inbox?${s}` : "/inbox";
}

export default async function Inbox({ searchParams }: { searchParams: Promise<{ queue?: string; status?: string; q?: string; page?: string }> }) {
  const { queue, status, q, page: pageParam } = await searchParams;
  const loaded = await dataLoaded();
  const [emails, accounts] = await Promise.all([
    loaded ? api.emails(q) : Promise.resolve([]),
    api.gmailAccounts().catch(() => []),
  ]);
  const filtered = emails.filter(e => (!queue || e.category === queue) && (!status || e.status === status));
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(Math.max(1, Number(pageParam) || 1), totalPages);
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const pageWindow = [...new Set([1, totalPages, page - 2, page - 1, page, page + 1, page + 2].filter(p => p >= 1 && p <= totalPages))].sort((a, b) => a - b);
  return <><div className="page-heading"><div><div className="eyebrow">Correspondence</div><h1>Your shipping inbox</h1><p>Find the message. Inspect the evidence. Make the next call.</p></div><div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:8}}><span className="badge dim">{filtered.length} messages</span><GmailControls accounts={accounts} mockLoaded={loaded}/><Link href="/inbox/new" className="btn ghost">+ Add email</Link></div></div>
    <form className="filters"><input aria-label="Search messages" name="q" defaultValue={q} placeholder="Search subject, sender, or email ID…"/><select aria-label="Queue" name="queue" defaultValue={queue ?? ""}><option value="">All queues</option>{Object.entries(QUEUES).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><select aria-label="Verdict" name="status" defaultValue={status ?? ""}><option value="">All verdicts</option>{Object.entries(STATUS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><button type="submit">Apply filters</button>{(q || queue || status) && <Link className="text-link" href="/inbox">Reset</Link>}</form>
    <div className="table-wrap"><table><thead><tr><th>Message</th><th>Queue</th><th>Finding</th><th>Source</th></tr></thead><tbody>{paged.map(e => <tr key={e.email_id}><td className="subject"><Link href={`/emails/${e.email_id}`}>{e.subject || "Untitled message"}</Link><small>{e.sender}</small><small className="mono">{e.email_id} · {e.n_attachments} attachments</small></td><td>{e.category ? QUEUES[e.category] ?? e.category : "—"}</td><td><StatusBadge status={e.status}/><small>{e.review_reason ? REASONS[e.review_reason] ?? e.review_reason : e.defect_fields?.map(f => FIELDS[f] ?? f).join(", ")}</small></td><td><span className="badge dim">{e.decided_by === "llm" ? "Model" : e.decided_by === "rule" ? "Rules" : "—"}</span></td></tr>)}</tbody></table>{!filtered.length && <div className="empty"><strong>{loaded ? "No messages found" : "Inbox is empty"}</strong>{loaded ? "Try another search or clear the filters." : "Load mock data or sync Gmail to display messages."}</div>}</div>
    {filtered.length > 0 && <nav className="pagination" aria-label="Inbox pages">
      {page > 1 ? <Link className="btn ghost" href={pageHref(page - 1, q, queue, status)}>← Prev</Link> : <span className="btn ghost disabled" aria-disabled="true">← Prev</span>}
      <div className="page-numbers">{pageWindow.map((p, i) => <span key={p} style={{display:"contents"}}>{i > 0 && pageWindow[i - 1] < p - 1 && <span className="page-gap">…</span>}<Link href={pageHref(p, q, queue, status)} className={`page-num${p === page ? " active" : ""}`} aria-current={p === page ? "page" : undefined}>{p}</Link></span>)}</div>
      <span className="muted">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
      {page < totalPages ? <Link className="btn ghost" href={pageHref(page + 1, q, queue, status)}>Next →</Link> : <span className="btn ghost disabled" aria-disabled="true">Next →</span>}
    </nav>}</>;
}
