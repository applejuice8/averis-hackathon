import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const runs = await api.runs();
  return (
    <>
      <h1>Pipeline runs</h1>
      <table>
        <thead>
          <tr><th>Run</th><th>Started</th><th>Results</th><th>Final score</th><th>End-to-end</th><th>Macro-F1</th></tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const score = r.score as any;
            const n = Object.values(r.stats ?? {}).reduce((a, b) => a + b, 0);
            return (
              <tr key={r.id}>
                <td>{r.id.slice(0, 8)}</td>
                <td>{new Date(r.started_at).toLocaleString()}</td>
                <td>{n}</td>
                <td>{score?.final_score !== undefined ? (score.final_score * 100).toFixed(1) + "%" : "—"}</td>
                <td>{score?.end_to_end ? `${score.end_to_end.success}/${score.end_to_end.total}` : "—"}</td>
                <td>{score?.stage1?.macro_f1 !== undefined ? (score.stage1.macro_f1 * 100).toFixed(1) + "%" : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
