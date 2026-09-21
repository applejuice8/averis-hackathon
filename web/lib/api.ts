// Same-origin browser requests are forwarded to the API by Next.js.
export const PUBLIC_API = "";

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
  error: string | null;
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

export type GmailPreviewItem = {
  message_id: string;
  subject: string;
  sender: string;
  date: string;
  attachments: string[];
  body: string;
};

export type SpamModelDetails = {
  model_name: string | null;
  framework: string;
  classifier: string | null;
  vectorizer: string | null;
  threshold: number;
  last_updated_at: string | null;
  training_records: number | null;
  spam_records: number | null;
  sklearn_version: string | null;
  evaluation_method: string | null;
  metrics: { accuracy: number; precision: number; recall: number; f1: number } | null;
  validation_runs: Array<{
    iteration: number;
    repeat: number;
    fold: number;
    training_records: number;
    validation_records: number;
    precision: number;
    recall: number;
    f1: number;
  }> | null;
  holdout: {
    records: number;
    spam_records: number;
    true_negatives: number;
    false_positives: number;
    false_negatives: number;
    true_positives: number;
  } | null;
};

async function get<T>(path: string): Promise<T> {
  const base = process.env.API_URL || (process.env.VERCEL ? "" : "http://localhost:8000");
  if (!base) throw new Error("API_URL must be configured for this deployment.");
  const r = await fetch(`${base.replace(/\/$/, "")}${path}`, { cache: "no-store", signal: AbortSignal.timeout(30_000) });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const api = {
  emails: (q?: string) => get<EmailListItem[]>(`/api/emails${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  email: (id: string) => get<EmailDetail>(`/api/emails/${id}`),
  calendar: () => get<CalendarItem[]>("/api/calendar"),
  runs: () => get<Run[]>("/api/runs"),
  review: () => get<ReviewItem[]>("/api/review"),
  gmailAccounts: () => get<GmailAccount[]>("/api/gmail/accounts"),
  spamModel: () => get<SpamModelDetails>("/api/spam/model"),
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

export type CompareField = (typeof COMPARE_FIELDS)[number];

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${PUBLIC_API}${path}`, { ...init, signal: AbortSignal.timeout(120000) });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}). Please try again.`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
