import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Support Resolution Copilot",
  description: "Full-stack RAG copilot for support teams"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <main className="container">
          <nav className="nav">
            <h1>AI Support Resolution Copilot</h1>
            <div className="nav-links">
              <Link href="/">Workspace</Link>
              <Link href="/admin">Admin</Link>
            </div>
          </nav>
          {children}
        </main>
      </body>
    </html>
  );
}
