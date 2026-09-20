"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";

// Reads a sample-format email file — {"from"|"sender", "subject", "body"} as
// JSON, or a text file starting with From:/Subject: header lines — and fills
// the form with it. Document files get attached with the picker below.
function parseEmailFile(text: string): { sender: string; subject: string; body: string } | null {
  try {
    const j = JSON.parse(text);
    if (j && typeof j === "object") {
      return { sender: String(j.sender ?? j.from ?? ""), subject: String(j.subject ?? ""), body: String(j.body ?? "") };
    }
  } catch { /* not JSON — try the header format */ }
  const m = text.match(/^\s*From:\s*(.+)\r?\nSubject:\s*(.+)\r?\n\r?\n([\s\S]+)$/i);
  return m ? { sender: m[1].trim(), subject: m[2].trim(), body: m[3].trim() } : null;
}

export default function EmailForm() {
  const router = useRouter();
  const importRef = useRef<HTMLInputElement>(null);
  const docRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [form, setForm] = useState({ sender: "", subject: "", body: "" });
  const [docs, setDocs] = useState<File[]>([]);

  function addDocs(list: FileList | null) {
    if (!list) return;
    setDocs(prev => {
      const seen = new Set(prev.map(f => `${f.name}:${f.size}`));
      return [...prev, ...Array.from(list).filter(f => !seen.has(`${f.name}:${f.size}`))];
    });
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    setError(""); setNote("");
    const parsed = parseEmailFile(await file.text());
    if (!parsed || !(parsed.sender || parsed.subject || parsed.body)) {
      setError('Could not read that file. Use the sample JSON format — {"from", "subject", "body"} — or a text file starting with From: and Subject: lines.');
      return;
    }
    setForm(parsed);
    setNote(`Imported ${file.name} — attach its documents below, then save.`);
  }

  async function submit() {
    setBusy(true); setError(""); setNote("");
    try {
      const fd = new FormData();
      fd.set("sender", form.sender.trim());
      fd.set("subject", form.subject.trim());
      fd.set("body", form.body);
      for (const f of docs) fd.append("files", f, f.name);
      const r = await request<{ email_id: string }>("/api/emails", { method: "POST", body: fd });
      router.refresh();
      router.push(`/emails/${r.email_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the email.");
      setBusy(false);
    }
  }

  const ready = form.sender.trim() || form.subject.trim() || form.body.trim();

  return <section className="panel">
    <div className="upload-fields">
      <div className="field-row">
        <input aria-label="Sender" placeholder="From — e.g. docs@vitalsolutions.sg" value={form.sender} onChange={e => setForm({...form, sender: e.target.value})} maxLength={300}/>
        <input aria-label="Subject" placeholder="Subject" value={form.subject} onChange={e => setForm({...form, subject: e.target.value})} maxLength={500}/>
      </div>
      <textarea aria-label="Body" rows={8} placeholder="Email body…" value={form.body} onChange={e => setForm({...form, body: e.target.value})}/>
      <div>
        <div className="section-heading" style={{marginTop:4}}><h2 style={{margin:0}}>Documents</h2><button type="button" className="ghost" onClick={() => docRef.current?.click()}>Attach documents</button></div>
        <input ref={docRef} type="file" multiple accept=".txt,.pdf,.docx,.xlsx" style={{display:"none"}} onChange={e => { addDocs(e.target.files); e.target.value = ""; }}/>
        {docs.length ? <div className="file-chips">{docs.map((f, i) => <span className="file-chip" key={`${f.name}-${i}`}><span className="mono">{f.name}</span><small className="muted">{Math.max(1, Math.round(f.size / 1024))} KB</small><button type="button" aria-label={`Remove ${f.name}`} onClick={() => setDocs(docs.filter((_, j) => j !== i))}>×</button></span>)}</div>
          : <p className="muted">No documents yet — attach the files that came with the email (SI, draft BL, invoice…). They are paired by content, so names do not matter.</p>}
      </div>
      <div className="actions">
        <button type="button" disabled={busy || !ready} onClick={submit}>{busy ? "Adding…" : "Add to inbox"}</button>
        <span className="muted">or</span>
        <button type="button" className="ghost" onClick={() => importRef.current?.click()}>Import a .txt / .json email file</button>
        <input ref={importRef} type="file" accept=".txt,.json" style={{display:"none"}} onChange={e => { importFile(e.target.files?.[0]); e.target.value = ""; }}/>
      </div>
      <div aria-live="polite" className="feedback">{note && <span className="success">{note}</span>}</div>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  </section>;
}
