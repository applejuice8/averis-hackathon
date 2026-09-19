import type { CSSProperties } from "react";
import { COMPARE_FIELDS, type CompareField } from "@/lib/api";
import { FIELDS } from "@/lib/labels";

type Match = { field: CompareField; start: number; end: number; defect: boolean };

const FIELD_COLORS: Record<CompareField, string> = {
  shipper: "#c8a34a",
  consignee: "#76a8df",
  notify_party: "#b6a1e8",
  port_of_loading: "#67c59a",
  port_of_discharge: "#65c3d3",
  container_count: "#d991bc",
  gross_weight_kg: "#df9b62",
};

function locate(text: string, field: CompareField, value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  if (field === "container_count" || field === "gross_weight_kg") {
    const n = Number(value);
    if (!Number.isFinite(n)) return null;
    for (const candidate of [Math.round(n).toLocaleString("en-US"), String(Math.round(n))]) {
      const start = text.indexOf(candidate);
      if (start >= 0) return { start, end: start + candidate.length };
    }
    return null;
  }
  const needle = String(value).trim();
  if (!needle) return null;
  const haystack = text.toLowerCase();
  let start = haystack.indexOf(needle.toLowerCase());
  if (start >= 0) return { start, end: start + needle.length };
  const token = needle.split(/\s+/)[0];
  if (token.length < 3) return null;
  start = haystack.indexOf(token.toLowerCase());
  return start >= 0 ? { start, end: start + token.length } : null;
}

function matchesFor(text: string, fields: Record<string, unknown>, defectFields: string[]) {
  const matches: Match[] = [];
  for (const field of COMPARE_FIELDS) {
    const found = locate(text, field, fields[field]);
    if (found) matches.push({ field, ...found, defect: defectFields.includes(field) });
  }
  matches.sort((a, b) => a.start - b.start);
  const nonOverlapping: Match[] = [];
  let cursor = -1;
  for (const match of matches) {
    if (match.start >= cursor) {
      nonOverlapping.push(match);
      cursor = match.end;
    }
  }
  return nonOverlapping;
}

export default function HighlightedText({ text, fields, defectFields = [] }: { text: string; fields: Record<string, unknown>; defectFields?: string[] }) {
  const matches = matchesFor(text, fields ?? {}, defectFields);
  if (!matches.length) return <pre>{text}</pre>;
  const parts: { text: string; match?: Match }[] = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start > cursor) parts.push({ text: text.slice(cursor, match.start) });
    parts.push({ text: text.slice(match.start, match.end), match });
    cursor = match.end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return <pre className="annotated-text">{parts.map((part, index) => part.match ? <span key={index} className={`field-hit ${part.match.defect ? "defect" : ""}`} style={{ "--field-color": FIELD_COLORS[part.match.field] } as CSSProperties}>{part.text}<span>{FIELDS[part.match.field]}</span></span> : <span key={index}>{part.text}</span>)}</pre>;
}
