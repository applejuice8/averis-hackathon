"use client";
import { useState } from "react";
import { SpamModelDetails } from "@/lib/api";

function percentage(value: number | undefined): string {
  return value === undefined ? "Not recorded" : `${(value * 100).toFixed(1)}%`;
}

export default function ModelDetails({ model }: { model: SpamModelDetails | null }) {
  const [open, setOpen] = useState(false);
  const metrics = model?.metrics ?? undefined;
  return <>
    <button type="button" className="ghost" onClick={() => setOpen(true)}>Model details</button>
    {open && <div role="dialog" aria-modal="true" aria-label="Spam model details"
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50, padding: 16 }}
      onClick={() => setOpen(false)}>
      <section className="panel" style={{ width: "min(720px, 96vw)", maxHeight: "86vh", overflow: "auto", padding: 24 }} onClick={event => event.stopPropagation()}>
        <div className="section-heading" style={{ marginTop: 0 }}><div><div className="eyebrow">Spam classifier</div><h2 style={{ margin: "6px 0 0" }}>Model details</h2></div><button type="button" className="ghost" onClick={() => setOpen(false)}>Close</button></div>
        {!model ? <div className="empty"><strong>Model unavailable</strong>The packaged scikit-learn artifact could not be loaded.</div> : <>
          <div className="cards" style={{ marginTop: 20 }}>
            <div className="card"><span className="lbl">Accuracy</span><div className="num">{percentage(metrics?.accuracy)}</div><small>Recorded evaluation</small></div>
            <div className="card"><span className="lbl">Precision</span><div className="num">{percentage(metrics?.precision)}</div><small>Recorded evaluation</small></div>
            <div className="card"><span className="lbl">Recall</span><div className="num">{percentage(metrics?.recall)}</div><small>Recorded evaluation</small></div>
            <div className="card"><span className="lbl">F1 score</span><div className="num">{percentage(metrics?.f1)}</div><small>Recorded evaluation</small></div>
          </div>
          {metrics ? <p className="muted">{model.evaluation_method}. These results describe the synthetic dataset and do not measure performance on unseen production email.</p> : <p className="muted">Evaluation metrics were not recorded in this artifact. They will be included after the next training run.</p>}
          <div className="table-wrap" style={{ marginTop: 20 }}><table><tbody>
            <tr><th>Model</th><td>{model.model_name ?? "Not recorded"}</td></tr>
            <tr><th>Framework</th><td>{model.framework}{model.sklearn_version ? ` ${model.sklearn_version}` : ""}</td></tr>
            <tr><th>Pipeline</th><td>{model.vectorizer ?? "Unknown vectorizer"} → {model.classifier ?? "Unknown classifier"}</td></tr>
            <tr><th>Decision threshold</th><td>{model.threshold.toFixed(3)}</td></tr>
            <tr><th>Training records</th><td>{model.training_records?.toLocaleString() ?? "Not recorded"}</td></tr>
            <tr><th>Spam records</th><td>{model.spam_records?.toLocaleString() ?? "Not recorded"}</td></tr>
            <tr><th>Evaluation</th><td>{model.evaluation_method ?? "Not recorded"}</td></tr>
            <tr><th>Last updated</th><td>{model.last_updated_at ? new Date(model.last_updated_at).toLocaleString() : "Not recorded"}</td></tr>
          </tbody></table></div>
        </>}
      </section>
    </div>}
  </>;
}
