import Link from "next/link";
import EmailForm from "./EmailForm";
export const dynamic = "force-dynamic";
export default function NewEmail() {
  return <>
    <Link className="text-link" href="/inbox">← Back to inbox</Link>
    <div className="page-heading" style={{marginTop:20}}><div><div className="eyebrow">Manual intake</div><h1>Add an email</h1><p>Drop a message into the inbox and attach the documents that came with it — SI, BL, invoice or anything else. The email is triaged by the next pipeline run.</p></div></div>
    <EmailForm/>
  </>;
}
