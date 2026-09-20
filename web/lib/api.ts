const API = process.env.API_URL || "http://localhost:8000";
// Same-origin browser requests are forwarded to the API by Next.js.
export const PUBLIC_API = process.env.NEXT_PUBLIC_API_URL || "";

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
    result_id: string;
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

export type CalendarItem = {
  email_id: string;
  date: string;
  source: string;
  subject: string;
  sender: string;
  category: string | null;
  status: string | null;
};

export type GmailAccount = {
  id: string;
  google_email: string | null;
  last_synced_at: string | null;
  created_at: string | null;
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
  gmailAccounts: () => get<GmailAccount[]>("/api/gmail/accounts"),
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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${PUBLIC_API}${path}`, { ...init, signal: AbortSignal.timeout(120000) });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}). Please try again.`);
  }
  return response.json();
}
