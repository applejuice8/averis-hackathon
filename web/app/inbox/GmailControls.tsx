"use client";
import { Fragment, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GmailAccount, GmailPreviewItem, request } from "@/lib/api";
import { LockedHint, useReviewer } from "../components/Reviewer";

const WINDOWS = [
  { days: 1, label: "Past 1 day" },
  { days: 2, label: "Past 2 days" },
  { days: 7, label: "Past 7 days" },
  { days: 14, label: "Past 14 days" },
  { days: 30, label: "Past 30 days" },
];

const FILE_TYPES = [
  { value: "", label: "All types" },
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word" },
  { value: "xlsx", label: "Excel" },
  { value: "txt", label: "Text" },
];

const SORTS = [
  { value: "date_desc", label: "Newest first" },
  { value: "date_asc", label: "Oldest first" },
  { value: "subject", label: "Subject A–Z" },
  { value: "sender", label: "Sender A–Z" },
];

const GROUPS = [
  { value: "none", label: "No grouping" },
  { value: "day", label: "By day" },
  { value: "week", label: "By week" },
  { value: "month", label: "By month" },
];

// override the global button background so .text-link's accent text is visible
const linkBtn: React.CSSProperties = { background: "transparent", border: "none", padding: 0 };

function parseDate(s: string): Date | null {
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function fmtDate(s: string): string {
  const d = parseDate(s);
  return d
    ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : s || "—";
}

function fileExt(name: string): string {
  const m = name.toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : "";
}

function startOfWeek(d: Date): Date {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Monday = 0
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}

function groupKey(d: Date | null, mode: string): string {
  if (!d) return "Unknown date";
  if (mode === "day") return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  if (mode === "week") return `Week of ${startOfWeek(d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
  if (mode === "month") return d.toLocaleDateString(undefined, { year: "numeric", month: "long" });
  return "";
}

export default function GmailControls({ accounts }: { accounts: GmailAccount[] }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [loadingMock, setLoadingMock] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [days, setDays] = useState(1);
  const [preview, setPreview] = useState<GmailPreviewItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [fileType, setFileType] = useState("");
  const [sortBy, setSortBy] = useState("date_desc");
  const [groupBy, setGroupBy] = useState("none");
  const [active, setActive] = useState<GmailPreviewItem | null>(null);
  const connected = accounts[0] ?? null;

  // lock page scroll while the modal is open so scrolling stays inside it
  useEffect(() => {
    if (preview === null) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [preview]);

  function connect() {
    // /api/* is rewritten to the API, which 302s to Google's consent screen.
    window.location.href = "/api/auth/google/start";
  }

  async function loadMockData() {
    setLoadingMock(true); setError(""); setNotice("");
    try {
      const result = await request<{ loaded: number }>("/api/emails/mock", { method: "POST" });
      setNotice(`Loaded ${result.loaded} mock message${result.loaded === 1 ? "" : "s"}.`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load mock data.");
    } finally { setLoadingMock(false); }
  }

  async function openPreview() {
    setBusy(true); setError(""); setNotice("");
    try {
      const items = await request<GmailPreviewItem[]>(`/api/gmail/preview?days=${days}`);
      setPreview(items);
      setSelected(new Set(items.map(i => i.message_id))); // default: all checked
      setSearch(""); setFileType(""); setSortBy("date_desc"); setGroupBy("none"); setActive(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load Gmail messages.");
    } finally { setBusy(false); }
  }

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function setForItems(ids: string[], on: boolean) {
    setSelected(prev => {
      const next = new Set(prev);
      for (const id of ids) { if (on) next.add(id); else next.delete(id); }
      return next;
    });
  }

  function close() { setPreview(null); setSelected(new Set()); setActive(null); }

  async function importSelected() {
    setImporting(true); setError("");
    try {
      await request<{ synced: number }>("/api/gmail/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_ids: [...selected] }),
      });
      close();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gmail import failed.");
    } finally { setImporting(false); }
  }

  if (!connected) {
    return <div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="ghost" onClick={loadMockData} disabled={loadingMock || !unlocked}>{loadingMock ? "Loading…" : "Load mock data"}</button>
        <button onClick={connect} disabled={loadingMock}>Import from Gmail</button>
      </div>
      <LockedHint action="load mock data"/>
      {notice && <p className="muted" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>;
  }

  const items = preview ?? [];
  const q = search.trim().toLowerCase();
  const visible = items
    .filter(it => !fileType || it.attachments.some(a => fileExt(a) === fileType))
    .filter(it => !q || `${it.subject} ${it.sender} ${it.attachments.join(" ")}`.toLowerCase().includes(q));
  const sorted = [...visible].sort((a, b) => {
    if (sortBy === "subject") return (a.subject || "").localeCompare(b.subject || "");
    if (sortBy === "sender") return (a.sender || "").localeCompare(b.sender || "");
    const ta = parseDate(a.date)?.getTime() ?? 0;
    const tb = parseDate(b.date)?.getTime() ?? 0;
    return sortBy === "date_asc" ? ta - tb : tb - ta;
  });

  const groups: { key: string; items: GmailPreviewItem[] }[] = [];
  if (groupBy === "none") {
    groups.push({ key: "", items: sorted });
  } else {
    const map = new Map<string, GmailPreviewItem[]>();
    for (const it of sorted) {
      const k = groupKey(parseDate(it.date), groupBy);
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(it);
    }
    for (const [key, its] of map) groups.push({ key, items: its });
  }

  return <div>
    <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end" }}>
      <select aria-label="Sync window" value={days} onChange={e => setDays(Number(e.target.value))} disabled={busy || loadingMock}>
        {WINDOWS.map(w => <option key={w.days} value={w.days}>{w.label}</option>)}
      </select>
      <button type="button" className="ghost" onClick={loadMockData} disabled={busy || loadingMock || !unlocked}>{loadingMock ? "Loading…" : "Load mock data"}</button>
      <button onClick={openPreview} disabled={busy || loadingMock}>{busy ? "Loading…" : "Sync Gmail"}</button>
    </div>
    <LockedHint action="load mock data"/>
    <p className="muted" style={{ fontSize: 11 }}>
      {connected.google_email}{connected.last_synced_at ? ` · last synced ${new Date(connected.last_synced_at).toLocaleString()}` : " · not synced yet"}
    </p>
    {notice && <p className="muted" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}

    {preview !== null && (
      <div role="dialog" aria-modal="true" aria-label="Select emails to import"
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50, padding: 16 }}
        onClick={close}>
        <div className="panel" style={{ width: "min(1120px, 96vw)", height: "86vh", display: "flex", flexDirection: "column", padding: 20, textAlign: "left" }}
          onClick={e => e.stopPropagation()}>
          <h2 style={{ marginTop: 0 }}>Select emails to import</h2>
          <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{items.length} message{items.length === 1 ? "" : "s"} with attachments in the past {days} day{days === 1 ? "" : "s"}. Check the ones to bring in — click a row to read it on the right.</p>
          {items.length === 0
            ? <div className="empty" style={{ marginTop: 16 }}><strong>No emails found</strong>Widen the window and try again.</div>
            : <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0 6px" }}>
                <input aria-label="Search emails" placeholder="Search subject, sender, or file…" value={search} onChange={e => setSearch(e.target.value)} style={{ flex: "1 1 180px", minWidth: 140 }} />
                <select aria-label="Filter by attachment type" value={fileType} onChange={e => setFileType(e.target.value)}>
                  {FILE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
                <select aria-label="Sort emails" value={sortBy} onChange={e => setSortBy(e.target.value)}>
                  {SORTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
                <select aria-label="Group emails" value={groupBy} onChange={e => setGroupBy(e.target.value)}>
                  {GROUPS.map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
                </select>
              </div>
              <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "2px 0 10px" }}>
                <button type="button" className="text-link" style={linkBtn} onClick={() => setForItems(sorted.map(i => i.message_id), true)}>Select all</button>
                <button type="button" className="text-link" style={linkBtn} onClick={() => setSelected(new Set())}>Clear</button>
                <small className="muted" style={{ marginLeft: "auto" }}>{sorted.length} of {items.length} shown · {selected.size} selected</small>
              </div>
              <div style={{ display: "flex", gap: 16, flex: 1, minHeight: 0 }}>
                <div style={{ flex: "1.5 1 0", minWidth: 0, overflow: "auto", overscrollBehavior: "contain" }}>
                  {sorted.length === 0
                    ? <div className="empty"><strong>No emails match</strong>Adjust the search or filter.</div>
                    : <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th style={{ width: 34 }}></th>
                            <th>Subject</th>
                            <th>From</th>
                            <th>Date</th>
                          </tr>
                        </thead>
                        <tbody>
                          {groups.map(group => <Fragment key={group.key || "all"}>
                            {group.key && <tr>
                              <td colSpan={4} style={{ background: "#f9fafb" }}>
                                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                                  <strong style={{ fontSize: 12 }}>{group.key}</strong>
                                  <small className="muted">{group.items.length}</small>
                                  <button type="button" className="text-link" style={{ ...linkBtn, marginLeft: "auto" }} onClick={() => setForItems(group.items.map(i => i.message_id), true)}>Select</button>
                                  <button type="button" className="text-link" style={linkBtn} onClick={() => setForItems(group.items.map(i => i.message_id), false)}>Clear</button>
                                </div>
                              </td>
                            </tr>}
                            {group.items.map(item => {
                              const on = selected.has(item.message_id);
                              const isActive = active?.message_id === item.message_id;
                              return <tr key={item.message_id} onClick={() => setActive(item)} title="Click to preview"
                                style={{ cursor: "pointer", userSelect: "none", opacity: on ? 1 : 0.5, background: isActive ? "#eef4f2" : undefined, boxShadow: isActive ? "inset 3px 0 0 var(--accent)" : undefined }}>
                                <td><input type="checkbox" checked={on} onChange={() => toggle(item.message_id)} onClick={e => e.stopPropagation()} /></td>
                                <td className="subject" style={{ overflowWrap: "anywhere" }}>
                                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>{item.subject || "Untitled message"}</span>
                                  <small className="mono">{item.attachments.join(", ") || "—"}</small>
                                </td>
                                <td style={{ maxWidth: 170, overflowWrap: "anywhere" }}>{item.sender}</td>
                                <td style={{ whiteSpace: "nowrap" }}>{fmtDate(item.date)}</td>
                              </tr>;
                            })}
                          </Fragment>)}
                        </tbody>
                      </table>
                    </div>}
                </div>
                <aside style={{ flex: "1 1 0", minWidth: 0, overflow: "auto", overscrollBehavior: "contain", borderLeft: "1px solid var(--border)", paddingLeft: 16 }}>
                  {active === null
                    ? <div className="empty" style={{ height: "100%", display: "flex", flexDirection: "column", justifyContent: "center" }}><strong>Click an email to read it</strong>The full message and its attachments show here.</div>
                    : <div>
                      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                        <h3 style={{ margin: 0, fontSize: 15, overflowWrap: "anywhere", flex: 1 }}>{active.subject || "Untitled message"}</h3>
                        <button type="button" className={selected.has(active.message_id) ? "ghost" : ""} style={{ padding: "6px 10px", fontSize: 12, whiteSpace: "nowrap" }} onClick={() => toggle(active.message_id)}>
                          {selected.has(active.message_id) ? "Remove" : "Add to import"}
                        </button>
                      </div>
                      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0", overflowWrap: "anywhere" }}>{active.sender}</p>
                      <p className="muted" style={{ fontSize: 12, margin: "2px 0 0" }}>{fmtDate(active.date)}</p>
                      {active.attachments.length > 0 && <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "12px 0" }}>
                        {active.attachments.map(a => <span key={a} className="badge info mono">{a}</span>)}
                      </div>}
                      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: "inherit", fontSize: 13, lineHeight: 1.6, margin: "12px 0 0", userSelect: "text" }}>{active.body || "(no text body)"}</pre>
                    </div>}
                </aside>
              </div>
            </>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center", marginTop: 16 }}>
            <LockedHint action="import Gmail messages"/>
            <button type="button" className="ghost" onClick={close} disabled={importing}>Cancel</button>
            <button type="button" onClick={importSelected} disabled={importing || selected.size === 0 || !unlocked}>
              {importing ? "Importing…" : `Import selected (${selected.size})`}
            </button>
          </div>
        </div>
      </div>
    )}
  </div>;
}
