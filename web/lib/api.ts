const API = process.env.API_URL || "http://localhost:8000";

export type EmailListItem = {
  email_id: string;
  sender: string;
  subject: string;
  n_attachments: number;
  category: string | null;
  status: string | null;
  has_defect: boolean | null;
  defect_fields: string[] | null;
  review_reason: string | null;
  decided_by: string | null;
};

export type EmailDetail = {
  email_id: string;
  sender: string;
  subject: string;
  body: string;
  attachments: string[];
  result: {
    category: string;
    decided_by: string;
    status: string;
    review_reason: string | null;
    has_defect: boolean;
    defect_fields: string[];
    si_fields: Record<string, unknown> | null;
    bl_fields: Record<string, unknown> | null;
    doc_types: Record<string, string> | null;
    evidence: Record<string, unknown> | null;
    error: string | null;
  } | null;
};

export type Run = {
  id: string;
  label: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, number> | null;
  score: Record<string, unknown> | null;
};

export type ReviewItem = {
  result_id: string;
  email_id: string;
  status: string;
  review_reason: string | null;
  evidence: Record<string, unknown> | null;
  error: string | null;
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const api = {
  emails: (q?: string) => get<EmailListItem[]>(`/api/emails${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  email: (id: string) => get<EmailDetail>(`/api/emails/${id}`),
  runs: () => get<Run[]>("/api/runs"),
  review: () => get<ReviewItem[]>("/api/review"),
};

export const COMPARE_FIELDS = [
  "shipper",
  "consignee",
  "notify_party",
  "port_of_loading",
  "port_of_discharge",
  "container_count",
  "gross_weight_kg",
] as const;
