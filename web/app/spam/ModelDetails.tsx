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
      <section className="panel" style={{ width: "min(960px, 96vw)", maxHeight: "86vh", overflow: "auto", padding: 24 }} onClick={event => event.stopPropagation()}>
        <div className="section-heading" style={{ marginTop: 0 }}><div><div className="eyebrow">Spam classifier</div><h2 style={{ margin: "6px 0 0" }}>Model details</h2></div><button type="button" className="ghost" onClick={() => setOpen(false)}>Close</button></div>
        {!model ? <div className="hero-note bad" style={{ margin: "20px 0 0" }}><div><strong>Model unavailable</strong><p>The packaged scikit-learn artifact could not be loaded.</p></div></div> : <>
          <div className="cards" style={{ marginTop: 20 }}>
            <div className="card"><span className="lbl">Accuracy</span><div className="num">{percentage(metrics?.accuracy)}</div><small>Recorded evaluation</small></div>
            <div className="card"><span className="lbl">Precision</span><div className="num">{percentage(metrics?.precision)}</div><small>Recorded evaluation</small></div>
            <div className="card"><span className="lbl">Recall</span><div className="num">{percentage(metrics?.recall)}</div><small>Recorded evaluation</small></div>
            <div className="card"><span className="lbl">F1 score</span><div className="num">{percentage(metrics?.f1)}</div><small>Recorded evaluation</small></div>
          </div>
          {metrics ? <div className="hero-note warn" style={{ margin: "18px 0 0" }}><div><strong>Perfect here does not mean perfect in production</strong><p>{model.evaluation_method}. The data is synthetic and has only nine unique spam subjects and six unique spam bodies, so shared generator patterns can still hide overfitting.</p></div></div> : <p className="muted">Evaluation metrics were not recorded in this artifact. They will be included after the next training run.</p>}
          {model.validation_runs && <><div className="section-heading"><div><div className="eyebrow">Repeated cross-validation</div><h3 style={{ margin: "6px 0 0" }}>Individual validation runs</h3></div><span className="badge dim">{model.validation_runs.length} runs</span></div><p className="muted">Each row is a separately held-out fold. Training and validation records never overlap within a run.</p><div className="table-wrap"><table><thead><tr><th>Run</th><th>Repeat</th><th>Fold</th><th>Train</th><th>Validate</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{model.validation_runs.map(run => <tr key={run.iteration}><td>{run.iteration}</td><td>{run.repeat}</td><td>{run.fold}</td><td>{run.training_records}</td><td>{run.validation_records}</td><td>{percentage(run.precision)}</td><td>{percentage(run.recall)}</td><td>{percentage(run.f1)}</td></tr>)}</tbody></table></div></>}
          {model.holdout && <><div className="section-heading"><div><div className="eyebrow">Final independent check</div><h3 style={{ margin: "6px 0 0" }}>Untouched holdout</h3></div><span className="badge dim">{model.holdout.records} messages</span></div><div className="cards"><div className="card"><span className="lbl">Spam messages</span><div className="num">{model.holdout.spam_records}</div><small>in holdout</small></div><div className="card"><span className="lbl">True positives</span><div className="num">{model.holdout.true_positives}</div><small>spam caught</small></div><div className="card"><span className="lbl">True negatives</span><div className="num">{model.holdout.true_negatives}</div><small>legitimate cleared</small></div><div className="card"><span className="lbl">Errors</span><div className="num">{model.holdout.false_positives + model.holdout.false_negatives}</div><small>{model.holdout.false_positives} FP · {model.holdout.false_negatives} FN</small></div></div></>}
          <div className="section-heading"><h3>Artifact details</h3></div><div className="table-wrap"><table><tbody>
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
