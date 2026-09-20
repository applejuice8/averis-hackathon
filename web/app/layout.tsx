import "./globals.css";
import Navigation from "./components/Navigation";

export const metadata = { title: "SDOC · Document operations", description: "Review shipping documents with source evidence and clear, field-level decisions." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><a className="skip-link" href="#main">Skip to content</a><Navigation /><div className="workspace"><header className="topbar"><span>Shipping operations <span className="muted">/ Document verification</span></span><span className="badge dim">SI → Draft BL</span></header><main id="main">{children}</main><footer>SDOC Verifier <span>AI-assisted reading. Deterministic comparison. Human oversight.</span></footer></div></body></html>;
}
