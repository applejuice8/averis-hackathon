import Link from "next/link";
import { api } from "@/lib/api";
import ModelDetails from "./ModelDetails";

export const dynamic = "force-dynamic";
const PAGE_SIZE = 10;

function pageHref(page: number) {
  return page > 1 ? `/spam?page=${page}` : "/spam";
}

export default async function SpamPage({ searchParams }: { searchParams: Promise<{ page?: string }> }) {
  const { page: pageParam } = await searchParams;
  const [emails, model] = await Promise.all([api.emails(), api.spamModel().catch(() => null)]);
  const spam = emails.filter(email => email.category === "SPAM");
  const totalPages = Math.max(1, Math.ceil(spam.length / PAGE_SIZE));
  const page = Math.min(Math.max(1, Number(pageParam) || 1), totalPages);
  const paged = spam.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const pageWindow = [...new Set([1, totalPages, page - 2, page - 1, page, page + 1, page + 2].filter(value => value >= 1 && value <= totalPages))].sort((a, b) => a - b);
  return <>
    <div className="page-heading"><div><div className="eyebrow">Automated protection</div><h1>Spam detection</h1><p>Messages flagged by the trained scikit-learn classifier before other inbox rules run.</p></div><div style={{ display: "flex", alignItems: "center", gap: 10 }}><span className="badge dim">{spam.length} flagged</span><ModelDetails model={model}/></div></div>
    <div className={`hero-note${model ? "" : " bad"}`}><div><strong>{model ? "Scikit-learn model active" : "Spam model unavailable"}</strong><p>{model ? `${model.vectorizer} and ${model.classifier} score sender, subject, and body text at a ${model.threshold.toFixed(3)} threshold.` : "Messages will continue through deterministic classification rules until the artifact is restored."}</p></div></div>
    <div className="table-wrap"><table><thead><tr><th>Message</th><th>Sender</th><th>Decision source</th><th>Finding</th></tr></thead><tbody>{paged.map(email => <tr key={email.email_id}><td className="subject"><Link href={`/emails/${email.email_id}`}>{email.subject || "Untitled message"}</Link><small className="mono">{email.email_id}</small></td><td>{email.sender}</td><td><span className="badge info">{email.decided_by === "ml" ? "Scikit-learn" : email.decided_by ?? "—"}</span></td><td>Spam</td></tr>)}</tbody></table>{!spam.length && <div className="empty"><strong>No spam detected</strong>Messages classified as spam by the model will appear here.</div>}</div>
    {spam.length > 0 && <nav className="pagination" aria-label="Spam pages">
      {page > 1 ? <Link className="btn ghost" href={pageHref(page - 1)}>← Prev</Link> : <span className="btn ghost disabled" aria-disabled="true">← Prev</span>}
      <div className="page-numbers">{pageWindow.map((value, index) => <span key={value} style={{ display: "contents" }}>{index > 0 && pageWindow[index - 1] < value - 1 && <span className="page-gap">…</span>}<Link href={pageHref(value)} className={`page-num${value === page ? " active" : ""}`} aria-current={value === page ? "page" : undefined}>{value}</Link></span>)}</div>
      <span className="muted">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, spam.length)} of {spam.length}</span>
      {page < totalPages ? <Link className="btn ghost" href={pageHref(page + 1)}>Next →</Link> : <span className="btn ghost disabled" aria-disabled="true">Next →</span>}
    </nav>}
  </>;
}
