import "./globals.css";
import Navigation from "./components/Navigation";
import Observability from "./components/Observability";

export const metadata = { title: "DockerOps · Shipping document operations", description: "DockerOps is an AI copilot for shipping-document operations.", icons: { icon: "/dockerops.png" } };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><a className="skip-link" href="#main">Skip to content</a><Navigation /><div className="workspace"><header className="topbar"><span>Shipping operations <span className="muted">/ Document verification</span></span><span className="badge dim">SI → Draft BL</span></header><main id="main">{children}</main><footer>DockerOps <span>AI-assisted reading. Deterministic comparison. Human oversight.</span></footer></div><Observability /></body></html>;
}
