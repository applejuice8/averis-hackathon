import Link from "next/link";
import { api } from "@/lib/api";
import { QUEUES, REASONS } from "@/lib/labels";
import StatusBadge from "./components/StatusBadge";
export const dynamic = "force-dynamic";
export default async function Dashboard() {
  const [emails, runs] = await Promise.all([api.emails(), api.runs()]);
  const processed = emails.filter(e => e.status);
  const checks = emails.filter(e => e.category === "BL_COMPARISON");
  const mismatches = emails.filter(e => e.status === "MISMATCH");
  const review = emails.filter(e => ["NEEDS_REVIEW", "FAILED"].includes(e.status ?? ""));
  const attention = [...review, ...mismatches].slice(0, 5);
  const rules = processed.filter(e => e.decided_by === "rule").length;
  const models = processed.filter(e => e.decided_by === "llm").length;
  return <>
    <div className="page-heading"><div><div className="eyebrow">Your operations, in view</div><h1>A clearer path to shipment.</h1><p>Catch document issues before the draft Bill of Lading is finalized.</p></div><Link href="/inbox" className="btn">Open inbox ↗</Link></div>
    <div className="cards">{[
      ["Inbox volume", emails.length, `${processed.length} emails triaged`, "▤", "/inbox"],
      ["Document checks", checks.length, "Shipping instruction → draft BL", "◫", "/inbox?queue=BL_COMPARISON"],
      ["Mismatches found", mismatches.length, "Compare against the SI reference", "≠", "/inbox?status=MISMATCH"],
      ["Awaiting review", review.length, "A human decision is needed", "◎", "/review"],
    ].map(([label,value,note,icon,href]) => <Link className="card" key={label} href={String(href)}><div className="metric-top"><span className="lbl">{label}</span><span className="metric-icon">{icon}</span></div><div className="num">{value}</div><small>{note}</small></Link>)}</div>
    <div className="hero-note"><span className="hero-icon" aria-hidden="true">◎</span><div><strong>{review.length ? `${review.length} cases need a second look` : "Every detail deserves a clear decision"}</strong><p>Missing files, unreadable documents, and incomplete details go to human review.</p></div><Link href="/review" className="text-link">Review cases →</Link></div>
    <div className="grid2"><section><div className="section-heading"><h2>Needs your attention</h2><Link className="text-link" href="/inbox">View inbox →</Link></div><div className="table-wrap"><table><thead><tr><th>Shipment correspondence</th><th>Finding</th></tr></thead><tbody>{attention.map(e => <tr key={e.email_id}><td className="subject"><Link href={`/emails/${e.email_id}`}>{e.subject}</Link><small>{e.email_id} · {e.sender}</small></td><td><StatusBadge status={e.status}/><small>{e.review_reason ? REASONS[e.review_reason] ?? e.review_reason : `${e.defect_fields?.length ?? 0} fields differ`}</small></td></tr>)}</tbody></table>{!attention.length && <div className="empty"><strong>{processed.length ? "Nothing waiting here" : "Ready for the first run"}</strong>{processed.length ? "No mismatches or escalations in the current results." : "Ingest your inbox and run the pipeline to see findings."}</div>}</div><div className="section-heading"><h2>How decisions were made</h2><span className="badge dim">Classification source</span></div><div className="panel"><div className="actions"><strong>{rules} by rules</strong><span className="muted">/</span><strong>{models} by model</strong></div><div className="bar"><span style={{width:`${processed.length ? rules / processed.length * 100 : 0}%`}} /></div><p className="muted">Models help read and classify. Field comparisons run in code; reviewers make corrections.</p></div></section>
    <div className="stack"><section className="panel"><h2>Inbox breakdown</h2>{Object.entries(QUEUES).map(([q,label]) => <Link className="queue-row" key={q} href={`/inbox?queue=${q}`}><span>{label}</span><strong>{emails.filter(e => e.category === q).length} <span className="muted">↗</span></strong></Link>)}</section><section className="panel"><div className="eyebrow">Pipeline activity</div><h2 style={{marginTop:8}}>{runs[0] ? runs[0].finished_at ? "Latest run complete" : "Processing inbox" : "No runs yet"}</h2><p className="muted">{runs[0] ? runs[0].label || runs[0].id.slice(0,8) : "Start a run once the inbox is ingested."}</p><Link className="text-link" href="/runs">View runs →</Link></section></div></div>
  </>;
}
