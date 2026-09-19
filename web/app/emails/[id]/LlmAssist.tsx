"use client";

import { useState } from "react";
import { PUBLIC_API } from "@/lib/api";

export default function LlmAssist({ emailId }: { emailId: string }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const r = await fetch(`${PUBLIC_API}/api/pipeline/llm-assist/${emailId}`);
      setData(await r.json());
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2>AI assist (on demand)</h2>
      <p className="dim">
        Live OpenRouter inference — classification, field extraction, and
        vision OCR for scanned attachments. Does not change the verdict.
      </p>
      <button className="btn" onClick={run} disabled={busy}>
        {busy ? "Running models…" : data ? "Re-run AI assist" : "Run AI assist"}
      </button>
      {data && <pre>{JSON.stringify(data, null, 2)}</pre>}
    </>
  );
}
