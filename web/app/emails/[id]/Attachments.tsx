"use client";
import { useState } from "react";
import { request } from "@/lib/api";
import HighlightedText from "./HighlightedText";

type Preview = {
  name: string;
  text: string;
  readable: boolean;
  error: string | null;
  truncated: boolean;
  doc_type: string | null;
  fields: Record<string, unknown>;
};

export default function Attachments({ emailId, files, defectFields = [] }: { emailId: string; files: string[]; defectFields?: string[] }) {
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
  return <section className="panel evidence-panel"><h2>Source documents</h2><p className="muted">Open an attachment to verify extracted fields in context. Outlined highlights indicate fields flagged by the comparison.</p><div className="attachment-tabs">{files.map((file, i) => <button className={selected === i ? "" : "ghost"} key={file} disabled={busy} aria-pressed={selected === i} onClick={() => open(i)}>{file.split("/").pop()}</button>)}</div>{!files.length && <p className="muted">No attachments in this message.</p>}<div aria-live="polite">{busy && <p>Reading attachment...</p>}{data && <>{data.doc_type && <p className="muted">Detected document type: <strong>{data.doc_type}</strong></p>}{!data.readable && <p className="error">Preview unavailable: {data.error || "unreadable document"}. Check the original file.</p>}{data.text && <HighlightedText text={data.text} fields={data.fields} defectFields={defectFields} />} {data.truncated && <p className="muted">Preview limited to the first 50,000 characters.</p>}</>}</div>{error && <p role="alert" className="error">{error}</p>}</section>;
}
