import Link from "next/link";
import { api } from "@/lib/api";
import ModelDetails from "./ModelDetails";

export const dynamic = "force-dynamic";

export default async function SpamPage() {
  const [emails, model] = await Promise.all([api.emails(), api.spamModel().catch(() => null)]);
  const spam = emails.filter(email => email.category === "SPAM");
  return <>
    <div className="page-heading"><div><div className="eyebrow">Automated protection</div><h1>Spam detection</h1><p>Messages flagged by the trained scikit-learn classifier before other inbox rules run.</p></div><div style={{ display: "flex", alignItems: "center", gap: 10 }}><span className="badge dim">{spam.length} flagged</span><ModelDetails model={model}/></div></div>
    <div className="hero-note"><div><strong>{model ? "Scikit-learn model active" : "Spam model unavailable"}</strong><p>{model ? `${model.vectorizer} and ${model.classifier} score sender, subject, and body text at a ${model.threshold.toFixed(3)} threshold.` : "Messages will continue through deterministic classification rules until the artifact is restored."}</p></div></div>
    <div className="table-wrap"><table><thead><tr><th>Message</th><th>Sender</th><th>Decision source</th><th>Finding</th></tr></thead><tbody>{spam.map(email => <tr key={email.email_id}><td className="subject"><Link href={`/emails/${email.email_id}`}>{email.subject || "Untitled message"}</Link><small className="mono">{email.email_id}</small></td><td>{email.sender}</td><td><span className="badge info">{email.decided_by === "ml" ? "Scikit-learn" : email.decided_by ?? "—"}</span></td><td>Spam</td></tr>)}</tbody></table>{!spam.length && <div className="empty"><strong>No spam detected</strong>Messages classified as spam by the model will appear here.</div>}</div>
  </>;
}
