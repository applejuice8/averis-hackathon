"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { COMPARE_FIELDS, request } from "@/lib/api";
import { FIELDS } from "@/lib/labels";
import { LockedHint, useReviewer } from "../../components/Reviewer";

export default function ReviewActions({ resultId, status, defectFields, canCompare }: { resultId: string; status: string; defectFields: string[]; canCompare: boolean }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fields, setFields] = useState(defectFields);
  const [reviewer, setReviewer] = useState("");
  const locked = busy || !unlocked;
  async function act(action: string, payload?: Record<string, unknown>) {
    setBusy(true); setMessage(""); setError("");
    try {
      await request(`/api/review/${resultId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, payload, reviewer: reviewer.trim() || "ops" }) });
      setMessage(action === "confirm" ? "Verdict confirmed. Confirmation keeps the current status." : "Changes saved. The verdict has been updated.");
      router.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the review."); }
    finally { setBusy(false); }
  }
  return <section className="panel review-form"><h2>Reviewer decision</h2><p className="muted">Confirm the finding or correct it after checking the source documents.</p><LockedHint action="record a decision"/><div className="filters"><input aria-label="Reviewer name" placeholder="Reviewer name (optional)" value={reviewer} onChange={e => setReviewer(e.target.value)} maxLength={100} disabled={locked}/></div><div className="actions"><button disabled={locked} onClick={() => act("confirm")}>Confirm verdict</button>{status !== "OK" && <button className="ghost" disabled={locked} onClick={() => act("override_status", {status:"OK",review_reason:null})}>Mark clear</button>}{status !== "NEEDS_REVIEW" && <button className="ghost" disabled={locked} onClick={() => act("override_status", {status:"NEEDS_REVIEW",review_reason:"manual_flag"})}>Escalate to review</button>}</div>
    {canCompare && <details><summary>Correct the mismatch fields</summary><p className="muted">Select the fields that differ. Saving no fields marks the result clear.</p><div className="field-options">{COMPARE_FIELDS.map(f => <label key={f}><input type="checkbox" checked={fields.includes(f)} disabled={locked} onChange={e => setFields(previous => e.target.checked ? [...previous,f] : previous.filter(v => v !== f))}/>{FIELDS[f]}</label>)}</div><button className="ghost" disabled={locked} onClick={() => act("override_fields", {defect_fields:fields})}>Save field corrections</button></details>}
    <div aria-live="polite" className="feedback">{busy ? "Saving review…" : message && <span className="success">{message}</span>}</div>{error && <p className="error" role="alert">{error}</p>}
  </section>;
}
