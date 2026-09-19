"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PUBLIC_API } from "@/lib/api";

export default function ReviewActions({ resultId, status }: { resultId: string; status: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function act(action: string, payload?: Record<string, unknown>) {
    setBusy(action);
    try {
      await fetch(`${PUBLIC_API}/api/review/${resultId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, payload, reviewer: "ops" }),
      });
      setDone(action);
      router.refresh();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0" }}>
      <button className="btn" disabled={busy !== null} onClick={() => act("confirm")}>
        Confirm verdict
      </button>
      {status !== "OK" && (
        <button className="btn" disabled={busy !== null}
          onClick={() => act("override_status", { status: "OK", review_reason: null })}>
          Override → OK
        </button>
      )}
      {status !== "MISMATCH" && (
        <button className="btn" disabled={busy !== null}
          onClick={() => act("override_status", { status: "NEEDS_REVIEW", review_reason: "manual_flag" })}>
          Escalate to review
        </button>
      )}
      {busy && <span className="dim">saving…</span>}
      {done && !busy && <span className="badge dim">review recorded</span>}
    </div>
  );
}
