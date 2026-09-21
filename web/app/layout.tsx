import { cookies } from "next/headers";
import { REVIEWER_COOKIE, reviewerUnlocked } from "@/lib/server";
import "./globals.css";
import Navigation from "./components/Navigation";
import { ReviewerProvider } from "./components/Reviewer";

export const metadata = { title: "DockerOps · Shipping document operations", description: "DockerOps is an AI copilot for shipping-document operations.", icons: { icon: "/dockerops.png" } };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const passcode = (await cookies()).get(REVIEWER_COOKIE)?.value;
  const unlocked = await reviewerUnlocked(passcode);
  return <html lang="en"><body><ReviewerProvider unlocked={unlocked} hasPasscode={Boolean(passcode)}><a className="skip-link" href="#main">Skip to content</a><Navigation /><div className="workspace"><header className="topbar"><span>Shipping operations <span className="muted">/ Document verification</span></span><span className="badge dim">SI → Draft BL</span></header><main id="main">{children}</main><footer>DockerOps <span>AI-assisted reading. Deterministic comparison. Human oversight.</span></footer></div></ReviewerProvider></body></html>;
}
