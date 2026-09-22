"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { request } from "@/lib/api";

export default function RetryButton({ emailId, label = "Retry" }: { emailId: string; label?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function retry() {
    setBusy(true); setError("");
    try { await request(`/api/emails/${emailId}/reprocess`, { method: "POST" }); router.refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not reprocess this email."); }
    finally { setBusy(false); }
  }
  return <span className="retry"><button className="ghost" onClick={retry} disabled={busy}>{busy ? "Processing…" : label}</button>{error && <small className="error" role="alert">{error}</small>}</span>;
}
