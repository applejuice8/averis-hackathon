"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { CalendarItem } from "@/lib/api";
import { QUEUES, STATUS } from "@/lib/labels";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const CATEGORY_COLORS: Record<string, string> = {
  BL_COMPARISON: "#6eb5a5",
  SI_REQUEST: "#a5a0e8",
  INVOICE_QUERY: "#7db8df",
  GENERAL: "#8794a2",
  SPAM: "#e19090",
};

function keyFor(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export default function CalendarView({ items }: { items: CalendarItem[] }) {
  const byDate = useMemo(() => {
    const map: Record<string, CalendarItem[]> = {};
    for (const item of items) (map[item.date] ??= []).push(item);
    return map;
  }, [items]);

  const initial = useMemo(() => {
    const dates = items.map(item => item.date).sort();
    const anchor = dates.length ? new Date(`${dates[dates.length - 1]}T00:00:00`) : new Date();
    return { year: anchor.getFullYear(), month: anchor.getMonth() };
  }, [items]);

  const [{ year, month }, setView] = useState(initial);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const first = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < first.getDay(); i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) cells.push(new Date(year, month, day));
  while (cells.length % 7 !== 0) cells.push(null);

  function move(delta: number) {
    const next = new Date(year, month + delta, 1);
    setView({ year: next.getFullYear(), month: next.getMonth() });
    setSelectedDate(null);
  }

  const selectedItems = selectedDate ? byDate[selectedDate] ?? [] : [];

  return <>
    <div className="calendar-toolbar"><button className="ghost" onClick={() => move(-1)}>Previous</button><strong>{MONTHS[month]} {year}</strong><button className="ghost" onClick={() => move(1)}>Next</button><button className="ghost" onClick={() => { setView(initial); setSelectedDate(null); }}>Jump to activity</button></div>
    <div className="calendar-grid">{DAYS.map(day => <div className="calendar-day-name" key={day}>{day}</div>)}{cells.map((date, index) => {
      if (!date) return <div className="calendar-cell empty" key={index} />;
      const key = keyFor(date);
      const dayItems = byDate[key] ?? [];
      return <button type="button" className={`calendar-cell ${selectedDate === key ? "selected" : ""}`} key={key} onClick={() => setSelectedDate(dayItems.length ? key : null)}><span>{date.getDate()}</span>{dayItems.length > 0 && <><div className="calendar-markers">{dayItems.slice(0, 8).map((item, markerIndex) => <i key={`${item.email_id}-${markerIndex}`} style={{ background: CATEGORY_COLORS[item.category ?? "GENERAL"] ?? CATEGORY_COLORS.GENERAL }} />)}</div><small>{dayItems.length} email{dayItems.length === 1 ? "" : "s"}</small></>}</button>;
    })}</div>
    {selectedDate && <section className="panel calendar-list"><h2>{selectedDate}</h2>{selectedItems.map(item => <Link href={`/emails/${item.email_id}`} className="calendar-list-item" key={item.email_id}><span className="mono">{item.email_id}</span><strong>{item.subject}</strong><small>{QUEUES[item.category ?? ""] ?? item.category ?? "Untriaged"} · {STATUS[item.status ?? ""] ?? item.status ?? "Unprocessed"}</small></Link>)}</section>}
  </>;
}
