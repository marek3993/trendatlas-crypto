import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";
import { requireUser } from "@/lib/auth/require-user";

type Profile = { display_name: string | null };

export default async function DashboardPage() {
  const { supabase, user } = await requireUser();
  const { data } = await supabase.from("profiles").select("display_name").eq("id", user.id).maybeSingle<Profile>();
  const name = data?.display_name?.trim() || "there";

  return <main><div className="card">
    <div className="row"><strong>TrendAtlas</strong><LogoutButton /></div>
    <h1>Welcome, {name}</h1>
    <h2>Trading account</h2>
    <p className="muted">Not connected</p>
    <Link className="button" href="/onboarding">Connect Hyperliquid</Link>
    <p className="muted"><Link href="/settings">Settings</Link></p>
  </div></main>;
}
