"use client";
import { useRouter } from "next/navigation";
import { createContext, useContext, useState } from "react";

type Reviewer = { unlocked: boolean; hasPasscode: boolean };
const ReviewerContext = createContext<Reviewer>({ unlocked: false, hasPasscode: false });

/** Provides reviewer state as booleans only — the passcode itself never reaches the client. */
export function ReviewerProvider({ unlocked, hasPasscode, children }: Reviewer & { children: React.ReactNode }) {
  return <ReviewerContext.Provider value={{ unlocked, hasPasscode }}>{children}</ReviewerContext.Provider>;
}

export function useReviewer() {
  return useContext(ReviewerContext);
}

/** Explains what to do about a locked control, instead of just greying it out. */
export function LockedHint({ action }: { action: string }) {
  const { unlocked } = useReviewer();
  return unlocked ? null : <p className="locked-hint">Unlock reviewer mode in the sidebar to {action}.</p>;
}

export function ReviewerPanel() {
  const { unlocked, hasPasscode } = useReviewer();
  const router = useRouter();
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function unlock(event: React.FormEvent) {
    event.preventDefault();
    const attempt = passcode;
    // Clear the field immediately — the passcode never lingers in the input
    // or in component state beyond this one closure variable.
    setPasscode("");
    setBusy(true);
    setError("");
    try {
      const r = await fetch("/auth/reviewer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passcode: attempt }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        throw new Error(body?.detail ?? "Could not unlock reviewer mode.");
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not unlock reviewer mode.");
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    setBusy(true);
    setError("");
    await fetch("/auth/reviewer", { method: "DELETE" }).catch(() => null);
    setBusy(false);
    router.refresh();
  }

  if (unlocked && !hasPasscode) {
    return (
      <div className="reviewer-panel">
        <span><span className="status-dot" />Open access</span>
        <small>No reviewer passcode is configured for this deployment.</small>
      </div>
    );
  }

  if (unlocked) {
    return (
      <div className="reviewer-panel">
        <span><span className="status-dot" />Reviewer mode on</span>
        <button type="button" className="ghost" onClick={lock} disabled={busy}>{busy ? "Locking…" : "Lock"}</button>
      </div>
    );
  }

  return (
    <form className="reviewer-panel" onSubmit={unlock}>
      <label htmlFor="reviewer-passcode">Reviewer mode</label>
      {hasPasscode && !error && (
        <small>Your reviewer session expired or the passcode was rotated. Enter it again to keep editing.</small>
      )}
      <input
        id="reviewer-passcode"
        type="password"
        autoComplete="off"
        placeholder="Passcode"
        value={passcode}
        onChange={e => setPasscode(e.target.value)}
        maxLength={256}
        disabled={busy}
      />
      <button disabled={busy || !passcode}>{busy ? "Checking…" : "Unlock"}</button>
      {error && <small className="error" role="alert">{error}</small>}
      {!error && !hasPasscode && <small>Browsing is open. Unlock to save reviews, run checks, or use AI assist.</small>}
    </form>
  );
}
