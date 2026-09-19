import "./globals.css";
import Link from "next/link";

export const metadata = { title: "SDOC Verifier" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <span className="brand">SDOC Verifier</span>
          <Link href="/">Dashboard</Link>
          <Link href="/inbox">Inbox</Link>
          <Link href="/review">Review</Link>
          <Link href="/runs">Runs</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
