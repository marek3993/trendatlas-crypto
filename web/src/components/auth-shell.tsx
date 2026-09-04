import Link from "next/link";

export function AuthShell({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return (
    <main>
      <div className="card">
        <div className="row"><strong>TrendAtlas</strong><Link href="/login">Sign in</Link></div>
        <h1>{title}</h1>
        {children}
      </div>
    </main>
  );
}
