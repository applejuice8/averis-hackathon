"use client";
import { useState } from "react";
import { request } from "@/lib/api";
export default function LlmAssist({ emailId }: { emailId: string }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run() {
    setBusy(true); setError(""); setData(null);
    try { setData(await request<Record<string, unknown>>(`/api/pipeline/llm-assist/${emailId}`, { method: "POST" })); }
    catch (err) { setError(err instanceof Error ? err.message : "AI assist is unavailable."); }
    finally { setBusy(false); }
  }
  return <section className="panel"><div className="eyebrow">A second reading</div><h2 style={{marginTop:8}}>AI assist</h2><p className="muted">Ask the model to classify and extract details. Suggestions do not change the saved verdict.</p><button className="ghost" style={{marginTop:16}} onClick={run} disabled={busy}>{busy ? "Reading with AI…" : data ? "Run again" : "Run AI assist"}</button>{error && <p role="alert" className="error">{error}</p>}{data && <details open><summary>Model response</summary><pre>{JSON.stringify(data,null,2)}</pre></details>}</section>;
}
