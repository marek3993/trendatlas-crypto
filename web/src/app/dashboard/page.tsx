import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";
import { requireUser } from "@/lib/auth/require-user";
import { disconnectHyperliquidAccount } from "@/app/onboarding/actions";
import { displayHyperliquidAddress } from "@/lib/hyperliquid/address";
import { type HyperliquidAccountSnapshot } from "@/lib/hyperliquid/info";
import { getHyperliquidAccountPerformance, type HyperliquidAccountPerformance, type PerformanceWindow } from "@/lib/hyperliquid/performance";
import { RefreshPerformanceButton } from "@/components/refresh-performance-button";
import { AgentAuthorizationPanel } from "@/components/agent-authorization-panel";
import { executionMode } from "@/server/multi-account-executor/mode";

type Profile = { display_name: string | null };
type HyperliquidAccount = { id: string; master_address: string; connection_status: string };
type AgentAuthorization = { authorization_status: string; auto_trading_requested: boolean; execution_status: string };

function formatUsd(value: number | null): string {
  if (value === null) return "Unavailable";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function formatPercent(value: number | null): string {
  return value === null ? "Unavailable" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function positionSummary(positions: HyperliquidAccountSnapshot["positions"]): string {
  if (positions.length === 0) return "None";
  return positions.map(({ coin, size }) => `${coin} ${size}`).join(", ");
}

function windowLabel(label: string, window: PerformanceWindow) {
  if (!window.available) return <p>{label}: <span className="muted">Unavailable — more live history is needed.</span></p>;
  return <p>{label}: {formatUsd(window.pnlUsd)} <span className="muted">Return: {formatPercent(window.returnPct)}</span></p>;
}

export default async function DashboardPage() {
  const { supabase, user } = await requireUser();
  const { data } = await supabase.from("profiles").select("display_name").eq("id", user.id).maybeSingle<Profile>();
  const { data: account } = await supabase
    .from("hyperliquid_accounts")
    .select("id, master_address, connection_status")
    .eq("user_id", user.id)
    .maybeSingle<HyperliquidAccount>();
  const name = data?.display_name?.trim() || "there";
  const { data: authorization } = account ? await supabase
    .from("hyperliquid_agent_authorizations")
    .select("authorization_status, auto_trading_requested, execution_status")
    .eq("user_id", user.id)
    .eq("hyperliquid_account_id", account.id)
    .eq("authorization_status", "authorized")
    .maybeSingle<AgentAuthorization>() : { data: null };
  let performance: HyperliquidAccountPerformance | null = null;
  if (account?.connection_status === "read_only_connected") {
    try {
      performance = await getHyperliquidAccountPerformance(account.master_address);
    } catch {
      performance = null;
    }
  }

  return <main><div className="card">
    <div className="row"><strong>TrendAtlas</strong><LogoutButton /></div>
    <h1>Welcome, {name}</h1>
    <h2>Hyperliquid</h2>
    {account?.connection_status === "read_only_connected" ? <>
      <p className="notice">Read-only connected</p>
      <p>Address: {displayHyperliquidAddress(account.master_address)}</p>
      <AgentAuthorizationPanel authorization={authorization ? {
        authorizationStatus: authorization.authorization_status,
        autoTradingRequested: authorization.auto_trading_requested,
        executionStatus: authorization.execution_status,
        liveExecutorEnabled: executionMode() === "live"
      } : null} />
      {performance ? <>
        <h2>Performance</h2>
        <p>Capital: {formatUsd(performance.snapshot.accountEquityUsd)}</p>
        <p>Total live PnL: {formatUsd(performance.totalLivePnlUsd)}</p>
        {windowLabel("Today", performance.windows.today)}
        {windowLabel("30 days", performance.windows["30d"])}
        {windowLabel("90 days", performance.windows["90d"])}
        <h3>Breakdown</h3>
        <p>Trading PnL: {formatUsd(performance.breakdown?.tradingPnlUsd ?? null)}</p>
        <p>Fees: {formatUsd(performance.breakdown?.feesUsd ?? null)}</p>
        <p>Funding: {formatUsd(performance.breakdown?.fundingUsd ?? null)}</p>
        <p>Deposits: {formatUsd(performance.breakdown?.depositsUsd ?? null)}</p>
        <p>Withdrawals: {formatUsd(performance.breakdown?.withdrawalsUsd ?? null)}</p>
        <p>Cash-flow-adjusted return: {formatPercent(performance.cashFlowAdjustedReturnPct)}</p>
        <p className="muted">Live history begins {performance.liveGenesisDay ?? "when sufficient exchange history is available"} · {performance.historyDays} days</p>
        <p>Withdrawable: {formatUsd(performance.snapshot.withdrawableUsd)}</p>
        <p>Positions: {positionSummary(performance.snapshot.positions)}</p>
        <p>Open orders: {performance.snapshot.openOrderCount}</p>
        <RefreshPerformanceButton />
      </> : <p className="muted">Account data is temporarily unavailable.</p>}
      <form action={disconnectHyperliquidAccount}><button type="submit">Disconnect</button></form>
    </> : <>
      <p className="muted">Not connected</p>
      <Link className="button" href="/onboarding">Connect Hyperliquid</Link>
    </>}
    <p className="muted"><Link href="/settings">Settings</Link></p>
  </div></main>;
}
