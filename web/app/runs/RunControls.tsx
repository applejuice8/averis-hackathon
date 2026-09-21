"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { request, Run } from "@/lib/api";
import { LockedHint, useReviewer } from "../components/Reviewer";
export default function RunControls({ running }: { running: boolean }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [started, setStarted] = useState<string | null>(null);
  useEffect(() => {
    if (!running && !started) return;
    const timer = setInterval(async () => {
      router.refresh();
      if (started) {
        try {
          const run = await request<Run>(`/api/runs/${started}`);
          if (run.finished_at) setStarted(null);
        } catch { setError("Progress is temporarily unavailable. Refresh to check the run."); }
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [running, started, router]);
  async function start() {
    setBusy(true); setError("");
    try {
      const result = await request<{run_id:string}>("/api/pipeline/run?label=Workspace%20run", {method:"POST"});
      setStarted(result.run_id); router.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start the run."); }
    finally { setBusy(false); }
  }
  return <div><button onClick={start} disabled={busy || running || !!started || !unlocked}>{busy ? "Starting…" : running || started ? "Processing inbox…" : "Run inbox checks"}</button><LockedHint action="start a run"/>{error && <p className="error" role="alert">{error}</p>}<p className="muted" style={{fontSize:11}}>{running || started ? "Results refresh every few seconds." : "Uses the AI switches configured on the server."}</p></div>;
}
