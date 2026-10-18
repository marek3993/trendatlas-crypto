import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";
import { requireUser } from "@/lib/auth/require-user";

export default async function SettingsPage() {
  await requireUser();
  return <main><div className="card">
    <h1>Settings</h1>
    <p className="muted">Manage your account access here.</p>
    <p><Link href="/forgot-password">Change password</Link></p>
    <div className="row"><Link className="button" href="/dashboard">Back to dashboard</Link><LogoutButton /></div>
  </div></main>;
}
