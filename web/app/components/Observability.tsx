"use client";

import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";

// Page URLs go to Vercel with every event. The inbox search box puts free text
// in `?q=` (sender names, subjects), so drop the query string before sending.
// The path is enough to tell pages apart for traffic and Core Web Vitals.
function withoutQuery<T extends { url: string }>(event: T): T {
  return { ...event, url: event.url.split("?")[0] };
}

export default function Observability() {
  return (
    <>
      <Analytics beforeSend={withoutQuery} />
      <SpeedInsights beforeSend={withoutQuery} />
    </>
  );
}
