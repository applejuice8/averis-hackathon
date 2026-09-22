"use client";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navigation() {
  const path = usePathname();
  return <aside className="sidebar">
    <Link href="/" className="brand"><Image src="/dockerops.png" alt="" width={455} height={250} className="brand-logo" priority/><span>DockerOps<span className="brand-sub">SHIPPING DOCUMENT AI</span></span></Link>
    <div className="workspace-label">WORKSPACE</div>
    <nav aria-label="Main navigation">
      {[["/", "Overview", "◫"], ["/inbox", "Inbox", "▤"], ["/spam", "Spam", "!"], ["/calendar", "Calendar", "□"], ["/review", "Human review", "◎"], ["/runs", "Pipeline runs", "↗"]].map(([href, name, icon]) => <Link key={href} href={href} className={(href === "/" ? path === href : path.startsWith(href)) ? "active" : ""} aria-current={path === href ? "page" : undefined}><span aria-hidden="true">{icon}</span>{name}</Link>)}
    </nav>
    <div className="sidebar-note"><span className="status-dot" />Shipping instruction first<p>Verify every detail.<br />Keep the final call human.</p></div>
    <div className="workspace-user"><span className="avatar">OP</span><span>Operations workspace<small>Hackathon prototype</small></span></div>
  </aside>;
}
