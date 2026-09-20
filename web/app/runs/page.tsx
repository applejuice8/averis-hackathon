import { api, PUBLIC_API } from "@/lib/api";
import RunControls from "./RunControls";
export const dynamic = "force-dynamic";
type Score = { final_score?: number; end_to_end?: {success?: number; total?: number}; stage1?: {macro_f1?: number} };
export default async function RunsPage() {
  const runs = await api.runs();
  return <><div className="page-heading"><div><div className="eyebrow">Processing & evaluation</div><h1>Every run, accounted for.</h1><p>Track processing, inspect benchmark scores, and export the results.</p></div><RunControls running={runs.some(r => !r.finished_at)}/></div><div className="hero-note"><div><strong>Benchmarks describe the supplied dataset</strong><p>A high fixture score does not measure accuracy on unseen documents. Scores stay blank until the scorer is run.</p></div></div><div className="table-wrap"><table><thead><tr><th>Run</th><th>Progress</th><th>Results</th><th>Benchmark score</th><th>Defects caught</th><th>Export</th></tr></thead><tbody>{runs.map(r => {
    const score = r.score as Score | null;
    const n = Object.values(r.stats ?? {}).reduce((a,b) => a+b,0);
    return <tr key={r.id}><td><strong>{r.label || "Manual run"}</strong><small className="mono">{r.id.slice(0,8)}</small><small>{new Date(r.started_at).toLocaleString("en-GB", {timeZone:"UTC"})} UTC</small></td><td><span className={`badge ${r.finished_at ? "ok" : "warn"}`}>{r.finished_at ? "Complete" : "Running"}</span></td><td>{n} processed</td><td>{typeof score?.final_score === "number" ? `${(score.final_score*100).toFixed(1)}%` : "Not scored"}</td><td>{score?.end_to_end ? `${score.end_to_end.success ?? "—"}/${score.end_to_end.total ?? "—"}` : "—"}</td><td>{r.finished_at ? <a className="text-link" href={`${PUBLIC_API}/api/export/submission?run_id=${r.id}`} target="_blank" rel="noreferrer">JSON ↗</a> : <span className="muted">After completion</span>}</td></tr>;
  })}</tbody></table>{!runs.length && <div className="empty"><strong>No pipeline runs yet</strong>Ingest the inbox, then start your first check.</div>}</div></>;
}
