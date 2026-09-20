"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { GmailAccount, request } from "@/lib/api";

export default function GmailControls({ accounts }: { accounts: GmailAccount[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const connected = accounts[0] ?? null;

  function connect() {
    // /api/* is rewritten to the API, which 302s to Google's consent screen.
    window.location.href = "/api/auth/google/start";
  }

  async function sync() {
    setBusy(true); setError("");
    try {
      await request<{ synced: number }>("/api/gmail/sync", { method: "POST" });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gmail sync failed.");
    } finally { setBusy(false); }
  }

  if (!connected) {
    return <div><button onClick={connect}>Import from Gmail</button>{error && <p className="error" role="alert">{error}</p>}</div>;
  }
  return <div>
    <button onClick={sync} disabled={busy}>{busy ? "Syncing…" : "Sync Gmail"}</button>
    <p className="muted" style={{ fontSize: 11 }}>
      {connected.google_email}{connected.last_synced_at ? ` · last synced ${new Date(connected.last_synced_at).toLocaleString()}` : " · not synced yet"}
    </p>
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
