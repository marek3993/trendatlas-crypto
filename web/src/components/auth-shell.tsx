import Link from "next/link";

export function AuthShell({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return (
    <main>
      <div className="card">
        <div className="row">
          <strong>TrendAtlas</strong>
          <span className="auth-links"><Link href="/strategy">How it works</Link><Link href="/login">Sign in</Link></span>
        </div>
        <h1>{title}</h1>
        {children}
      </div>
    </main>
  );
}
