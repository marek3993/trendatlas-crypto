import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";
import { requireUser } from "@/lib/auth/require-user";
import { disconnectHyperliquidAccount } from "@/app/onboarding/actions";
import { displayHyperliquidAddress } from "@/lib/hyperliquid/address";
import { getHyperliquidAccountSnapshot, type HyperliquidAccountSnapshot } from "@/lib/hyperliquid/info";

type Profile = { display_name: string | null };
type HyperliquidAccount = { master_address: string; connection_status: string };

function formatUsd(value: number | null): string {
  if (value === null) return "Unavailable";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function positionSummary(positions: HyperliquidAccountSnapshot["positions"]): string {
  if (positions.length === 0) return "None";
  return positions.map(({ coin, size }) => `${coin} ${size}`).join(", ");
}

export default async function DashboardPage() {
  const { supabase, user } = await requireUser();
  const { data } = await supabase.from("profiles").select("display_name").eq("id", user.id).maybeSingle<Profile>();
  const { data: account } = await supabase
    .from("hyperliquid_accounts")
    .select("master_address, connection_status")
    .eq("user_id", user.id)
    .maybeSingle<HyperliquidAccount>();
  const name = data?.display_name?.trim() || "there";
  let snapshot: HyperliquidAccountSnapshot | null = null;
  if (account?.connection_status === "read_only_connected") {
    try {
      snapshot = await getHyperliquidAccountSnapshot(account.master_address);
    } catch {
      snapshot = null;
    }
  }

  return <main><div className="card">
    <div className="row"><strong>TrendAtlas</strong><LogoutButton /></div>
    <h1>Welcome, {name}</h1>
    <h2>Hyperliquid</h2>
    {account?.connection_status === "read_only_connected" ? <>
      <p className="notice">Connected</p>
      <p>Address: {displayHyperliquidAddress(account.master_address)}</p>
      {snapshot ? <>
        <p>Capital: {formatUsd(snapshot.accountEquityUsd)}</p>
        <p>Withdrawable: {formatUsd(snapshot.withdrawableUsd)}</p>
        <p>Positions: {positionSummary(snapshot.positions)}</p>
        <p>Open orders: {snapshot.openOrderCount}</p>
      </> : <p className="muted">Account data is temporarily unavailable.</p>}
      <form action={disconnectHyperliquidAccount}><button type="submit">Disconnect</button></form>
    </> : <>
      <p className="muted">Not connected</p>
      <Link className="button" href="/onboarding">Connect Hyperliquid</Link>
    </>}
    <p className="muted"><Link href="/settings">Settings</Link></p>
  </div></main>;
}
