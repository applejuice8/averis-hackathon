import { api } from "@/lib/api";
import { QUEUES } from "@/lib/labels";
import CalendarView from "./CalendarView";

export const dynamic = "force-dynamic";

export default async function CalendarPage() {
  const items = await api.calendar();
  const counts = items.reduce<Record<string, number>>((acc, item) => {
    const key = item.category ?? "UNTRIAGED";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  return <>
    <div className="page-heading"><div><div className="eyebrow">Calendar</div><h1>Operational dates</h1><p>Dates parsed from subjects and thread headers, grouped by day for planning and review.</p></div><span className="badge dim">{items.length} dated emails</span></div>
    <div className="cards">{Object.entries(counts).map(([category, count]) => <div className="card" key={category}><small>{QUEUES[category] ?? category}</small><div className="num">{count}</div><div className="lbl">dated emails</div></div>)}</div>
    {items.length ? <CalendarView items={items} /> : <section className="panel"><h2>No dated emails found</h2><p className="muted">Run ingestion and pipeline processing, then return here.</p></section>}
  </>;
}
