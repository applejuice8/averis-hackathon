"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";

type EmailPayload = { sender: string; subject: string; body: string; attachments: string[] };

// Accepts the sample bundle format — {"from"|"sender", "subject", "body",
// "attachments": [...]} — or a plain-text file with From:/Subject: headers,
// a blank line, then the body.
function parseEmailFile(text: string): EmailPayload | null {
  try {
    const j = JSON.parse(text);
    if (j && typeof j === "object") {
      return {
        sender: String(j.sender ?? j.from ?? ""),
        subject: String(j.subject ?? ""),
        body: String(j.body ?? ""),
        attachments: Array.isArray(j.attachments) ? j.attachments.map(String) : [],
      };
    }
  } catch { /* not JSON — try the header format */ }
  const m = text.match(/^\s*From:\s*(.+)\r?\nSubject:\s*(.+)\r?\n(?:Attachments?:\s*(.+)\r?\n)?\r?\n([\s\S]+)$/i);
  if (!m) return null;
  return {
    sender: m[1].trim(),
    subject: m[2].trim(),
    attachments: m[3] ? m[3].split(",").map(a => a.trim()).filter(Boolean) : [],
    body: m[4].trim(),
  };
}

export default function UploadEmail() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"fields" | "file">("fields");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({ sender: "", subject: "", body: "", attachments: "" });
  const [fileName, setFileName] = useState("");

  async function submit(payload: EmailPayload) {
    setBusy(true); setError(""); setMessage("");
    try {
      const r = await request<{ email_id: string }>("/api/emails", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setMessage(`Added ${r.email_id} — it will be picked up by the next run.`);
      setForm({ sender: "", subject: "", body: "", attachments: "" });
      setFileName("");
      if (fileRef.current) fileRef.current.value = "";
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the email.");
    } finally { setBusy(false); }
  }

  function submitFields() {
    submit({
      sender: form.sender.trim(),
      subject: form.subject.trim(),
      body: form.body,
      attachments: form.attachments.split(/[\n,]/).map(a => a.trim()).filter(Boolean),
    });
  }

  async function submitFile(file: File | undefined) {
    if (!file) return;
    setFileName(file.name); setError(""); setMessage("");
    const parsed = parseEmailFile(await file.text());
    if (!parsed || !(parsed.sender || parsed.subject || parsed.body)) {
      setError('Could not read that file. Use the sample JSON format — {"from", "subject", "body", "attachments"} — or a text file starting with From: and Subject: lines.');
      return;
    }
    submit(parsed);
  }

  const fieldsReady = form.sender.trim() || form.subject.trim() || form.body.trim();

  return <>
    <div className="add-email-bar"><button type="button" className="ghost" onClick={() => setOpen(o => !o)}>{open ? "Close" : "+ Add email"}</button></div>
    {open && <section className="panel add-email-panel">
      <div className="eyebrow">Manual intake</div>
      <h2 style={{marginTop:8}}>Add an email to the inbox</h2>
      <p className="muted">Enter the fields directly, or upload a .txt/.json file in the sample format — an id is assigned automatically and the message joins the next pipeline run.</p>
      <div className="attachment-tabs">
        <button type="button" className={mode === "fields" ? "" : "ghost"} onClick={() => setMode("fields")}>Fill in fields</button>
        <button type="button" className={mode === "file" ? "" : "ghost"} onClick={() => setMode("file")}>Upload file</button>
      </div>
      {mode === "fields" ? <div className="upload-fields">
        <div className="field-row">
          <input aria-label="Sender" placeholder="From — e.g. docs@vitalsolutions.sg" value={form.sender} onChange={e => setForm({...form, sender: e.target.value})} maxLength={300}/>
          <input aria-label="Subject" placeholder="Subject" value={form.subject} onChange={e => setForm({...form, subject: e.target.value})} maxLength={500}/>
        </div>
        <textarea aria-label="Body" rows={6} placeholder="Email body…" value={form.body} onChange={e => setForm({...form, body: e.target.value})}/>
        <input aria-label="Attachments" placeholder="Attachment paths, comma-separated (optional) — e.g. attachments/email_999_SI.txt" value={form.attachments} onChange={e => setForm({...form, attachments: e.target.value})}/>
        <div className="actions"><button type="button" disabled={busy || !fieldsReady} onClick={submitFields}>{busy ? "Adding…" : "Add to inbox"}</button></div>
      </div> : <div className="upload-file">
        <input ref={fileRef} aria-label="Email file" type="file" accept=".txt,.json" disabled={busy} onChange={e => submitFile(e.target.files?.[0])}/>
        {fileName && <p className="muted" style={{marginTop:10}}>{fileName}</p>}
      </div>}
      <div aria-live="polite" className="feedback">{message && <span className="success">{message}</span>}</div>
      {error && <p className="error" role="alert">{error}</p>}
    </section>}
  </>;
}
