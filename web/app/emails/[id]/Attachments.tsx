"use client";
import { useEffect, useMemo, useState } from "react";
import { request } from "@/lib/api";
import HighlightedText from "./HighlightedText";

type Preview = { name: string; text: string; readable: boolean; error: string | null; truncated: boolean };
type PreviewState = { file: string; preview: Preview | null; error: string | null };
type Props = {
  emailId: string;
  files: string[];
  defectFields?: string[];
  siFields?: Record<string, unknown> | null;
  blFields?: Record<string, unknown> | null;
  docTypes?: Record<string, string> | null;
  comparedFiles?: string[];
};

function roleFor(file: string, position: number, comparedFiles: string[], docTypes?: Record<string, string> | null) {
  const type = docTypes?.[file]?.toUpperCase();
  const name = file.toUpperCase();
  if (comparedFiles[0] === file || type === "SI" || name.includes("_SI")) return "SI";
  if (comparedFiles[1] === file || type === "BL" || name.includes("_BL")) return "BL";
  return position === 0 ? "SI" : position === 1 ? "BL" : "DOC";
}

export default function Attachments({ emailId, files, defectFields = [], siFields, blFields, docTypes, comparedFiles = [] }: Props) {
  const [previews, setPreviews] = useState<PreviewState[]>([]);
  const [activeField, setActiveField] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const orderedFiles = useMemo(() => {
    const compared = comparedFiles.filter(file => files.includes(file));
    return [...compared, ...files.filter(file => !compared.includes(file))];
  }, [comparedFiles, files]);

  useEffect(() => {
    let cancelled = false;
    setPreviews([]);
    if (!orderedFiles.length) return;
    setBusy(true);
    Promise.all(orderedFiles.map(async file => {
      const index = files.indexOf(file);
      try {
        return { file, preview: await request<Preview>(`/api/emails/${emailId}/attachments/${index}`), error: null };
      } catch (err) {
        return { file, preview: null, error: err instanceof Error ? err.message : "Could not load this attachment." };
      }
    })).then(data => {
      if (!cancelled) setPreviews(data);
    }).finally(() => {
      if (!cancelled) setBusy(false);
    });
    return () => { cancelled = true; };
  }, [emailId, files, orderedFiles]);

  return <section className="panel evidence-panel"><h2>Source documents</h2><p className="muted">Extracted values are highlighted in the source text. Outlined values are fields that failed comparison.</p>{!files.length && <p className="muted">No attachments in this message.</p>}<div className="document-evidence" aria-live="polite">{busy && !previews.length && <p>Reading attachments...</p>}{previews.map(({ file, preview, error }, position) => {
    const role = roleFor(file, position, comparedFiles, docTypes);
    const fields = role === "SI" ? siFields : role === "BL" ? blFields : null;
    const mirrorFields = role === "SI" ? blFields : role === "BL" ? siFields : null;
    return <article className="document-card" key={file}><header><div><span className="badge info">{role}</span><strong>{file.split("/").pop()}</strong></div>{docTypes?.[file] && <span className="badge dim">type: {docTypes[file]}</span>}</header>{error && <p role="alert" className="error">{error}</p>}{preview && <>{!preview.readable && <p className="error">Preview unavailable: {preview.error || "unreadable document"}. Check the original file.</p>}{preview.text && fields ? <HighlightedText text={preview.text} fields={fields} mirrorFields={mirrorFields} defectFields={defectFields} activeField={activeField} onActiveFieldChange={setActiveField} /> : preview.text ? <pre>{preview.text}</pre> : null}{preview.truncated && <p className="muted">Preview limited to the first 50,000 characters.</p>}</>}</article>;
  })}</div></section>;
}
