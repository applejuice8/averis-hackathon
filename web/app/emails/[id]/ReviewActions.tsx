"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { COMPARE_FIELDS, request } from "@/lib/api";
import { FIELDS, STATUS } from "@/lib/labels";
import { LockedHint, useReviewer } from "../../components/Reviewer";

type Decision = "" | "keep" | "clear" | "mismatch";

export default function ReviewActions({ resultId, status, defectFields, canCompare }: { resultId: string; status: string; defectFields: string[]; canCompare: boolean }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fields, setFields] = useState(defectFields);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<Decision>(status === "OK" || status === "MISMATCH" ? "keep" : "");
  const locked = busy || !unlocked;

  useEffect(() => { setFields(defectFields); }, [defectFields]);

  async function save() {
    if (!decision || !note.trim() || (decision === "mismatch" && fields.length === 0)) return;
    setBusy(true); setMessage(""); setError("");
    const action = decision === "keep" ? "confirm" : decision === "clear" ? "override_status" : "override_fields";
    const payload = decision === "clear"
      ? { status: "OK", review_reason: null }
      : decision === "mismatch" ? { defect_fields: fields } : undefined;
    try {
      const result = await request<{ status: string }>(`/api/review/${resultId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, payload, reviewer: reviewer.trim() || "ops", note: note.trim() }),
      });
      const fieldNames = fields.map(field => FIELDS[field] ?? field).join(", ");
      setMessage(result.status === "MISMATCH" ? `Saved. Final report: mismatch in ${fieldNames}.` : "Saved. Final report: no mismatch detected.");
      setDecision("keep");
      setNote("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the review.");
    } finally { setBusy(false); }
  }

  if (status === "FAILED") {
    return <section className="panel review-form"><h2>Reviewer decision</h2><div className="empty"><strong>Retry required</strong>Processing failed, so there is no dependable result to approve or correct. Retry the email first.</div></section>;
  }

  const canSave = Boolean(decision && note.trim() && (decision !== "mismatch" || fields.length > 0));
  return <section className="panel review-form">
    <div className="eyebrow">Human review</div><h2 style={{ marginTop: 8 }}>Finalize the report</h2>
    <p className="muted">Check the source documents, choose the final outcome, and record why. Saving updates the report and removes resolved cases from the review queue.</p>
    <div className="hero-note" style={{ margin: "16px 0" }}><div><strong>Current result: {STATUS[status] ?? status}</strong><p>{defectFields.length ? `Flagged fields: ${defectFields.map(field => FIELDS[field] ?? field).join(", ")}.` : "No mismatch fields are currently flagged."}</p></div></div>
    <LockedHint action="finalize this review"/>
    <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: "18px 0" }}>
      <legend style={{ fontWeight: 700, marginBottom: 8 }}>Final decision</legend>
      <div className="field-options" style={{ flexDirection: "column", alignItems: "flex-start", marginTop: 8 }}>
        {(status === "OK" || status === "MISMATCH") && <label><input type="radio" name="decision" checked={decision === "keep"} onChange={() => setDecision("keep")}/>Keep the current result</label>}
        <label><input type="radio" name="decision" checked={decision === "clear"} onChange={() => setDecision("clear")}/>{canCompare ? "No mismatch detected" : "Accept classification and close review"}</label>
        {canCompare && <label><input type="radio" name="decision" checked={decision === "mismatch"} onChange={() => setDecision("mismatch")}/>Mismatch found</label>}
      </div>
    </fieldset>
    {decision === "mismatch" && <div><strong>Fields that do not match</strong><p className="muted">Select every field where the SI and Bill of Lading differ.</p><div className="field-options">{COMPARE_FIELDS.map(field => <label key={field}><input type="checkbox" checked={fields.includes(field)} disabled={locked} onChange={event => setFields(previous => event.target.checked ? [...previous, field] : previous.filter(value => value !== field))}/>{FIELDS[field]}</label>)}</div>{fields.length === 0 && <small className="error">Select at least one mismatched field.</small>}</div>}
    <div className="filters" style={{ marginTop: 18 }}><input aria-label="Reviewer name" placeholder="Reviewer name (optional)" value={reviewer} onChange={event => setReviewer(event.target.value)} maxLength={100} disabled={locked}/></div>
    <label style={{ display: "grid", gap: 6, marginTop: 14 }}><strong>Decision note</strong><textarea aria-label="Decision note" placeholder="What did you verify in the source documents?" value={note} onChange={event => setNote(event.target.value)} maxLength={1000} rows={3} disabled={locked} required/></label>
    <button style={{ marginTop: 16 }} disabled={locked || !canSave} onClick={save}>{busy ? "Saving…" : "Save final decision"}</button>
    <div aria-live="polite" className="feedback">{message && <span className="success">{message}</span>}</div>{error && <p className="error" role="alert">{error}</p>}
  </section>;
}
