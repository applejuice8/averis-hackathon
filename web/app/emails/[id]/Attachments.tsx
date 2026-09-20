"use client";
import { useState } from "react";
import { request } from "@/lib/api";
type Preview = { name: string; text: string; readable: boolean; error: string | null; truncated: boolean };
export default function Attachments({ emailId, files }: { emailId: string; files: string[] }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [data, setData] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function open(index: number) {
    setSelected(index); setBusy(true); setError(""); setData(null);
    try { setData(await request<Preview>(`/api/emails/${emailId}/attachments/${index}`)); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load this attachment."); }
    finally { setBusy(false); }
  }
  return <section className="panel"><h2>Source documents</h2><p className="muted">Read the extracted document text alongside the comparison. SI is the reference.</p><div className="attachment-tabs">{files.map((file,i) => <button className={selected === i ? "" : "ghost"} key={file} disabled={busy} aria-pressed={selected === i} onClick={() => open(i)}>{file.split("/").pop()}</button>)}</div>{!files.length && <p className="muted">No attachments in this message.</p>}<div aria-live="polite">{busy && <p>Reading attachment…</p>}{data && <>{!data.readable && <p className="error">Preview unavailable: {data.error || "unreadable document"}. Check the original file.</p>}{data.text && <pre>{data.text}</pre>}{data.truncated && <p className="muted">Preview limited to the first 50,000 characters.</p>}</>}</div>{error && <p role="alert" className="error">{error}</p>}</section>;
}
