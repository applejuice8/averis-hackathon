import { FIELDS } from "@/lib/labels";

const SOURCES: Record<string, { label: string; description: string }> = {
  rule: { label: "Fixed rules", description: "The message matched a known shipping workflow." },
  ml: { label: "Spam model", description: "The spam model scored this message." },
  llm: { label: "AI fallback", description: "AI was used because the fixed rules were not certain." },
};

const CATEGORY_FINDINGS: Record<string, string> = {
  SPAM: "This message looks like spam.",
  SI_REQUEST: "This message asks for or includes a shipping instruction.",
  INVOICE_QUERY: "This message is about an invoice, charge, or payment.",
  GENERAL: "This message does not need a shipping document check.",
};

function value(value: unknown): string {
  return value == null || value === "" ? "missing" : String(value);
}

function fileName(path: unknown): string {
  return String(path).split("/").pop() || String(path);
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function findings({ category, status, reviewReason, defectFields, siFields, blFields, evidence }: EvidenceProps): string[] {
  if (status === "MISMATCH" && defectFields.length) {
    return defectFields.map(field => `${FIELDS[field] ?? field} mismatch: SI says “${value(siFields?.[field])}”; BL says “${value(blFields?.[field])}”.`);
  }

  if (reviewReason === "missing_attachment") return ["The shipping instruction or Bill of Lading is missing."];
  if (reviewReason === "unreadable") {
    const files = stringList(evidence?.files).map(fileName);
    return [files.length ? `We could not read ${files.join(" and ")}.` : "We could not read one or more documents."];
  }
  if (reviewReason === "wrong_doc_type") {
    const detected = objectValue(evidence?.detected);
    const messages = [];
    if (detected.si !== "SI") messages.push(`The shipping instruction file looks like ${value(detected.si)}.`);
    if (detected.bl !== "BL") messages.push(`The Bill of Lading file looks like ${value(detected.bl)}.`);
    return messages.length ? messages : ["One or more files are the wrong document type."];
  }
  if (reviewReason === "missing_value") {
    const fields = stringList(evidence?.blank_fields).map(field => FIELDS[field] ?? field);
    return [fields.length ? `${fields.join(" and ")} ${fields.length === 1 ? "is" : "are"} missing.` : "One or more required details are missing."];
  }
  if (category === "BL_COMPARISON") {
    return [siFields && blFields ? "The checked SI and Bill of Lading fields match." : "No document mismatch was found."];
  }
  return [CATEGORY_FINDINGS[category] ?? "No issue was found."];
}

type EvidenceProps = {
  category: string;
  status: string;
  reviewReason: string | null;
  decidedBy: string | null;
  defectFields: string[];
  siFields: Record<string, unknown> | null;
  blFields: Record<string, unknown> | null;
  evidence: Record<string, unknown> | null;
};

export default function EvidenceDetails(props: EvidenceProps) {
  const source = SOURCES[props.decidedBy ?? ""] ?? { label: "Unknown", description: "The decision source was not recorded." };
  const messages = findings(props);
  return <details className="panel">
    <summary>Why this result?</summary>
    <div style={{ display: "grid", gap: 18, marginTop: 18 }}>
      <section><div className="eyebrow">Finding</div><ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>{messages.map(message => <li key={message} style={{ marginTop: 6 }}>{message}</li>)}</ul></section>
      <section><div className="eyebrow">How it was checked</div><div className="actions" style={{ marginTop: 8 }}><span className="badge info">{source.label}</span><span className="muted">{source.description}</span></div></section>
      <p className="muted" style={{ margin: 0 }}>A reviewer can correct this result after checking the original documents.</p>
    </div>
  </details>;
}
