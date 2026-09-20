"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return <div className="panel empty" role="alert"><strong>We couldn’t load this workspace</strong><p>Check that the API and database are available, then try again.</p><button onClick={reset} style={{marginTop:20}}>Try again</button></div>;
}
