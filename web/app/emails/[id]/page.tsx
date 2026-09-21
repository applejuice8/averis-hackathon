import Link from "next/link";
import { notFound } from "next/navigation";
import { api, COMPARE_FIELDS } from "@/lib/api";
import { FIELDS, QUEUES, REASONS } from "@/lib/labels";
import { dataLoaded } from "@/lib/server";
import RetryButton from "../../components/RetryButton";
import StatusBadge from "../../components/StatusBadge";
import LlmAssist from "./LlmAssist";
import ReviewActions from "./ReviewActions";
import Attachments from "./Attachments";
import EvidenceDetails from "./EvidenceDetails";
export const dynamic = "force-dynamic";
export default async function EmailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!await dataLoaded()) notFound();
  const e = await api.email(id);
  const r = e.result;
  const comparedAttachments = Array.isArray(r?.evidence?.attachments) ? r.evidence.attachments.filter((file): file is string => typeof file === "string") : [];
  return <>
    <Link className="text-link" href="/inbox">← Back to inbox</Link><div className="page-heading" style={{ marginTop: 20 }}><div><div className="eyebrow">{e.email_id} · {r ? QUEUES[r.category] ?? r.category : "Awaiting triage"}</div><h1>{e.subject}</h1><p>From {e.sender}</p></div><div className="actions"><StatusBadge status={r?.status ?? null}/><RetryButton emailId={e.email_id} label="Reprocess"/></div></div>
    {r?.review_reason && <div className="hero-note"><strong>{REASONS[r.review_reason] ?? r.review_reason}</strong><span className="muted">Inspect the attachments before making a decision.</span></div>}
    {r?.error && <p className="error" role="alert">{r.error}</p>}
    {r?.si_fields && r?.bl_fields && <><div className="section-heading"><h2>Shipping instruction vs. draft BL</h2><span className="badge dim">7 fields · SI is the reference</span></div><div className="table-wrap"><table className="diff"><thead><tr><th>Field</th><th>Shipping instruction</th><th>Draft Bill of Lading</th><th>Finding</th></tr></thead><tbody>{COMPARE_FIELDS.map(f => {
      const diff = r.defect_fields.includes(f);
      const missing = r.si_fields?.[f] == null || r.bl_fields?.[f] == null || r.si_fields?.[f] === "" || r.bl_fields?.[f] === "";
      return <tr key={f}><td>{FIELDS[f]}</td><td className={diff ? "mismatch" : ""}>{String(r.si_fields?.[f] ?? "—")}</td><td className={diff ? "mismatch" : ""}>{String(r.bl_fields?.[f] ?? "—")}</td><td><span className={`badge ${missing ? "warn" : diff ? "bad" : "ok"}`}>{missing ? "Missing value" : diff ? "Differs" : "No flagged defect"}</span></td></tr>;
    })}</tbody></table></div></>}
    {r && <ReviewActions key={`${r.result_id}-${r.status}-${r.defect_fields.join()}`} resultId={r.result_id} status={r.status} defectFields={r.defect_fields} canCompare={r.category === "BL_COMPARISON"} />}
    <Attachments emailId={id} files={e.attachments} defectFields={r?.defect_fields ?? []} siFields={r?.si_fields ?? null} blFields={r?.bl_fields ?? null} docTypes={r?.doc_types ?? null} comparedFiles={comparedAttachments} />
    <LlmAssist emailId={id} />
    <details className="panel"><summary>Original email</summary><pre className="email-body">{e.body}</pre></details>
    {r && <EvidenceDetails category={r.category} status={r.status} reviewReason={r.review_reason} decidedBy={r.decided_by} defectFields={r.defect_fields} siFields={r.si_fields} blFields={r.bl_fields} evidence={r.evidence}/>}
  </>;
}
