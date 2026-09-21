import type { ReactNode } from "react";
import { FIELDS } from "@/lib/labels";

const SOURCES: Record<string, { label: string; description: string }> = {
  rule: { label: "Deterministic rules", description: "Matched transparent shipping-workflow rules." },
  ml: { label: "Scikit-learn model", description: "Scored by the trained spam classifier." },
  llm: { label: "Language model", description: "Classified by the configured language model fallback." },
};

const LABELS: Record<string, string> = {
  attachments: "Documents checked",
  files: "Unreadable files",
  errors: "Reading errors",
  detected: "Detected document types",
  blank_fields: "Missing required fields",
  si: "Shipping instruction",
  bl: "Bill of Lading",
};

const DOCUMENT_TYPES: Record<string, string> = {
  SI: "Shipping instruction",
  BL: "Bill of Lading",
  invoice: "Invoice",
  other: "Other document",
};

function labelFor(key: string): string {
  return FIELDS[key] ?? LABELS[key] ?? key.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase());
}

function scalar(value: unknown): string {
  if (value == null || value === "") return "Not detected";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return DOCUMENT_TYPES[value] ?? value;
  return String(value);
}

function EvidenceValue({ value }: { value: unknown }): ReactNode {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="muted">None</span>;
    return <div className="actions">{value.map((item, index) => <span className="badge dim" key={`${String(item)}-${index}`}>{FIELDS[String(item)] ?? scalar(item)}</span>)}</div>;
  }
  if (value && typeof value === "object") {
    return <dl style={{ display: "grid", gridTemplateColumns: "minmax(140px, 1fr) 2fr", gap: "8px 16px", margin: 0 }}>
      {Object.entries(value).map(([key, nested]) => <div key={key} style={{ display: "contents" }}><dt className="muted">{labelFor(key)}</dt><dd style={{ margin: 0 }}><EvidenceValue value={nested}/></dd></div>)}
    </dl>;
  }
  return scalar(value);
}

export default function EvidenceDetails({ decidedBy, evidence, docTypes }: { decidedBy: string | null; evidence: Record<string, unknown> | null; docTypes: Record<string, string> | null }) {
  const source = SOURCES[decidedBy ?? ""] ?? { label: "Unknown source", description: "No classification source was recorded." };
  const rationale = typeof evidence?.rationale === "string" ? evidence.rationale : null;
  const evidenceRows = Object.entries(evidence ?? {}).filter(([key]) => key !== "rationale");
  return <details className="panel">
    <summary>Detection evidence & classification source</summary>
    <div style={{ display: "grid", gap: 20, marginTop: 18 }}>
      <section><div className="eyebrow">Classification source</div><div className="actions" style={{ marginTop: 8 }}><span className="badge info">{source.label}</span><span className="muted">{source.description}</span></div></section>
      <section><div className="eyebrow">Why this decision was made</div><p style={{ marginBottom: 0 }}>{rationale ?? "No rationale was recorded for this result."}</p></section>
      {docTypes && Object.keys(docTypes).length > 0 && <section><div className="eyebrow">Document types</div><div style={{ marginTop: 8 }}><EvidenceValue value={docTypes}/></div></section>}
      {evidenceRows.length > 0 && <section><div className="eyebrow">Supporting evidence</div><dl style={{ display: "grid", gap: 14, margin: "10px 0 0" }}>{evidenceRows.map(([key, value]) => <div key={key}><dt style={{ fontWeight: 650 }}>{labelFor(key)}</dt><dd style={{ margin: "5px 0 0" }}><EvidenceValue value={value}/></dd></div>)}</dl></section>}
      <p className="muted" style={{ margin: 0 }}>Review actions may override the original verdict without changing this recorded machine evidence.</p>
    </div>
  </details>;
}
