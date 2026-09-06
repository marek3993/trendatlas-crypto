import Link from "next/link";
import { disconnectHyperliquidAccount } from "@/app/onboarding/actions";
import { AgentAuthorizationPanel } from "@/components/agent-authorization-panel";
import { LogoutButton } from "@/components/logout-button";
import { RefreshPerformanceButton } from "@/components/refresh-performance-button";
import { requireUser } from "@/lib/auth/require-user";
import { displayHyperliquidAddress } from "@/lib/hyperliquid/address";
import { type HyperliquidAccountSnapshot } from "@/lib/hyperliquid/info";
import { getHyperliquidAccountPerformance, type HyperliquidAccountPerformance, type PerformanceWindow } from "@/lib/hyperliquid/performance";
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

function formatAsOf(value: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Bratislava"
  }).format(value);
}

function positionSummary(positions: HyperliquidAccountSnapshot["positions"]): string {
  if (positions.length === 0) return "No open position";
  return positions.map(({ coin, size }) => `${coin} ${size}`).join(", ");
}

function accountAsset(positions: HyperliquidAccountSnapshot["positions"]): string {
  if (positions.length === 0) return "CASH";
  const assets = [...new Set(positions.map(({ coin }) => coin))];
  return assets.length === 1 ? assets[0] : `${assets.length} assets`;
}

function metricTone(value: number | null): string {
  if (value === null || value === 0) return "";
  return value > 0 ? " metric-card--positive" : " metric-card--negative";
}

function MetricCard({ label, value, detail, tone = "" }: { label: string; value: string; detail?: string; tone?: string }) {
  return <article className={`metric-card${tone}`}>
    <span className="metric-label">{label}</span>
    <strong className="metric-value">{value}</strong>
    {detail && <span className="metric-detail">{detail}</span>}
  </article>;
}

function WindowMetric({ label, window }: { label: string; window: PerformanceWindow }) {
  if (!window.available) return <MetricCard label={label} value="Unavailable" detail="More live history is needed" />;
  return <MetricCard
    label={label}
    value={formatUsd(window.pnlUsd)}
    detail={window.returnPct === null ? "Return unavailable" : formatPercent(window.returnPct)}
    tone={metricTone(window.pnlUsd)}
  />;
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

  const connected = account?.connection_status === "read_only_connected";
  const authorized = authorization?.authorization_status === "authorized";
  const autoTrading = authorization?.auto_trading_requested === true;
  const accountExecutionReady = ["ready", "aligned", "executing"].includes(authorization?.execution_status ?? "");
  const liveExecutorEnabled = executionMode() === "live" || process.env.TRENDATLAS_MULTI_ACCOUNT_EXECUTOR_AVAILABLE === "true";

  return <main className="dashboard-shell">
    <header className="dashboard-header">
      <Link className="dashboard-brand" href="/dashboard">TrendAtlas</Link>
      <nav className="dashboard-nav" aria-label="Account navigation">
        <Link className="active" href="/dashboard">Account</Link>
        <Link href="/settings">Settings</Link>
      </nav>
      <LogoutButton />
    </header>

    <section className="dashboard-intro">
      <p className="eyebrow">Private account dashboard</p>
      <h1>Welcome, {name}</h1>
      <p className="muted">Your Hyperliquid account, controls, positions and live performance in one place.</p>
    </section>

    {!connected ? <section className="dashboard-empty">
      <span className="status-dot" aria-hidden="true" />
      <div>
        <h2>Connect your Hyperliquid account</h2>
        <p className="muted">The dashboard will populate with your own balance, positions and performance after a read-only connection.</p>
      </div>
      <Link className="button" href="/onboarding">Connect Hyperliquid</Link>
    </section> : <>
      <section className="dashboard-section" aria-labelledby="controls-heading">
        <div className="section-heading">
          <div><p className="eyebrow">Account protection</p><h2 id="controls-heading">Status and controls</h2></div>
          <span className={`status-badge ${liveExecutorEnabled ? "status-badge--ready" : "status-badge--safe"}`}>
            {liveExecutorEnabled ? "Executor ready" : "Execution safely disabled"}
          </span>
        </div>

        <div className="control-panel">
          <div className="status-strip">
            <div><span>Automatic trades</span><strong>{autoTrading ? "Requested" : "Off"}</strong></div>
            <div><span>Real account</span><strong>{performance ? (performance.snapshot.positions.length ? "In market" : "Out of market") : "Unavailable"}</strong></div>
            <div><span>Account asset</span><strong>{performance ? accountAsset(performance.snapshot.positions) : "Unavailable"}</strong></div>
            <div><span>Open orders</span><strong>{performance?.snapshot.openOrderCount ?? "—"}</strong></div>
            <div><span>Order sending</span><strong>{liveExecutorEnabled && authorized && autoTrading && accountExecutionReady ? "Ready" : "Blocked"}</strong></div>
          </div>
          <AgentAuthorizationPanel authorization={authorization ? {
            authorizationStatus: authorization.authorization_status,
            autoTradingRequested: authorization.auto_trading_requested,
            executionStatus: authorization.execution_status,
            liveExecutorEnabled
          } : null} />
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="overview-heading">
        <div className="section-heading"><div><p className="eyebrow">Hyperliquid</p><h2 id="overview-heading">Overview</h2></div></div>
        <div className="overview-strip">
          <div><span>Connection</span><strong className="notice">Read-only connected</strong></div>
          <div><span>Last synchronization</span><strong>{performance ? formatAsOf(performance.asOfMs) : "Temporarily unavailable"}</strong></div>
          <div><span>Exchange</span><strong>Hyperliquid</strong></div>
        </div>
        <p className="account-address">Account address <strong>{displayHyperliquidAddress(account.master_address)}</strong></p>
      </section>

      {performance ? <>
        <section className="dashboard-section" aria-labelledby="balance-heading">
          <div className="section-heading"><div><p className="eyebrow">Wallet snapshot</p><h2 id="balance-heading">Balance</h2></div></div>
          <div className="metric-grid metric-grid--three">
            <MetricCard label="Total account value" value={formatUsd(performance.snapshot.accountEquityUsd)} detail="Exchange account equity" />
            <MetricCard label="Exchange withdrawable" value={formatUsd(performance.snapshot.withdrawableUsd)} detail="Exchange-native value" />
            <MetricCard label="Open positions" value={String(performance.snapshot.positions.length)} detail={accountAsset(performance.snapshot.positions)} />
            <MetricCard label="Open orders" value={String(performance.snapshot.openOrderCount)} detail="Current exchange orders" />
            <MetricCard label="Real exposure" value={performance.snapshot.positions.length === 0 ? "None" : "Active"} detail={positionSummary(performance.snapshot.positions)} />
            <MetricCard label="Data source" value="Live" detail="Hyperliquid read-only API" />
          </div>
        </section>

        <section className="dashboard-section" aria-labelledby="performance-heading">
          <div className="section-heading"><div><p className="eyebrow">Cash-flow adjusted</p><h2 id="performance-heading">Real account performance</h2></div></div>
          <div className="metric-grid metric-grid--five">
            <MetricCard label="Total live PnL" value={formatUsd(performance.totalLivePnlUsd)} detail="Since live history began" tone={metricTone(performance.totalLivePnlUsd)} />
            <MetricCard label="Live return" value={formatPercent(performance.cashFlowAdjustedReturnPct)} detail="Deposits and withdrawals excluded" tone={metricTone(performance.cashFlowAdjustedReturnPct)} />
            <WindowMetric label="Today" window={performance.windows.today} />
            <WindowMetric label="30 days" window={performance.windows["30d"]} />
            <WindowMetric label="90 days" window={performance.windows["90d"]} />
          </div>
          <p className="dashboard-note">Deposits and withdrawals are not counted as profit or loss.</p>
          <div className="metric-grid metric-grid--five metric-grid--compact">
            <MetricCard label="Trading PnL" value={formatUsd(performance.breakdown?.tradingPnlUsd ?? null)} tone={metricTone(performance.breakdown?.tradingPnlUsd ?? null)} />
            <MetricCard label="Funding" value={formatUsd(performance.breakdown?.fundingUsd ?? null)} tone={metricTone(performance.breakdown?.fundingUsd ?? null)} />
            <MetricCard label="Fees" value={formatUsd(performance.breakdown?.feesUsd ?? null)} tone={metricTone(performance.breakdown?.feesUsd ?? null)} />
            <MetricCard label="Deposits" value={formatUsd(performance.breakdown?.depositsUsd ?? null)} />
            <MetricCard label="Withdrawals" value={formatUsd(performance.breakdown?.withdrawalsUsd ?? null)} />
          </div>
          <p className="dashboard-note">Live history begins {performance.liveGenesisDay ?? "when sufficient exchange history is available"} · {performance.historyDays} days available</p>
        </section>

        <section className="dashboard-section dashboard-bottom-grid" aria-label="Position and account actions">
          <article className="detail-panel">
            <span className="metric-label">Position</span>
            <h3>{performance.snapshot.positions.length === 0 ? "No open position" : accountAsset(performance.snapshot.positions)}</h3>
            <p className="muted">{positionSummary(performance.snapshot.positions)}</p>
          </article>
          <article className="detail-panel">
            <span className="metric-label">Latest account state</span>
            <h3>{performance.snapshot.openOrderCount === 0 ? "No open orders" : `${performance.snapshot.openOrderCount} open orders`}</h3>
            <p className="muted">Updated {formatAsOf(performance.asOfMs)}</p>
          </article>
        </section>
      </> : <section className="dashboard-empty dashboard-empty--inline">
        <div><h2>Account data is temporarily unavailable</h2><p className="muted">Your connection is intact. Try refreshing the exchange data.</p></div>
      </section>}

      <section className="dashboard-actions" aria-label="Account actions">
        <RefreshPerformanceButton />
        <form action={disconnectHyperliquidAccount}><button className="button-secondary" type="submit">Disconnect account</button></form>
      </section>
    </>}
  </main>;
}
