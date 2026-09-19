import { STATUS } from "@/lib/labels";
export default function StatusBadge({ status }: { status: string | null }) {
  const tone = status === "OK" ? "ok" : status === "NEEDS_REVIEW" ? "warn" : ["MISMATCH", "FAILED"].includes(status ?? "") ? "bad" : "dim";
  return <span className={`badge ${tone}`}>{status ? STATUS[status] ?? status : "Unprocessed"}</span>;
}
