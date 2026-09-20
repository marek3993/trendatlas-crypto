import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";
import { requireUser } from "@/lib/auth/require-user";

type ExecutionRun = {
  canonical_closed_day: string;
  strategy_version: string;
  authorized_target_asset: string;
  authorized_target_exposure: number;
  status: string;
  completed_at: string | null;
};

function formatTimestamp(value: string | null): string {
  if (!value) return "Not completed";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Bratislava"
  }).format(new Date(value));
}

export default async function StrategyPage() {
  const { supabase, user } = await requireUser();
  const { data: latestRun } = await supabase
    .from("multi_account_execution_runs")
    .select("canonical_closed_day, strategy_version, authorized_target_asset, authorized_target_exposure, status, completed_at")
    .eq("user_id", user.id)
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle<ExecutionRun>();

  return <main className="dashboard-shell strategy-shell">
    <header className="dashboard-header">
      <Link className="dashboard-brand" href="/dashboard">TrendAtlas</Link>
      <nav className="dashboard-nav" aria-label="Account navigation">
        <Link href="/dashboard">Account</Link>
        <Link className="active" href="/strategy">Strategy</Link>
        <Link href="/settings">Settings</Link>
      </nav>
      <LogoutButton />
    </header>

    <section className="dashboard-intro">
      <p className="eyebrow">Current production logic</p>
      <h1>How TrendAtlas trades</h1>
      <p className="muted">The rules below describe the production model currently connected to the Raspberry Pi executor. They are operational facts, not a promise of profit.</p>
    </section>

    <section className="strategy-status" aria-labelledby="personal-status-heading">
      <div>
        <p className="eyebrow">Your latest recorded cycle</p>
        <h2 id="personal-status-heading">{latestRun ? latestRun.status.replaceAll("_", " ") : "No cycle recorded yet"}</h2>
      </div>
      {latestRun ? <dl className="strategy-facts">
        <div><dt>Closed market day</dt><dd>{latestRun.canonical_closed_day}</dd></div>
        <div><dt>Authorized target</dt><dd>{latestRun.authorized_target_asset} · {Number(latestRun.authorized_target_exposure).toFixed(2)}×</dd></div>
        <div><dt>Completed</dt><dd>{formatTimestamp(latestRun.completed_at)}</dd></div>
      </dl> : <p className="muted">A personal execution record appears after your account is connected, authorized and processed by the production cycle.</p>}
    </section>

    <section className="strategy-grid">
      <article className="strategy-card">
        <span className="metric-label">1 · Daily decision</span>
        <h2>One controlled target, or cash</h2>
        <p>The model evaluates closed daily market data and produces one authorized target for the next production cycle. The multi-account executor accepts only <strong>BTC, ETH or CASH</strong>. An unsupported or ambiguous target is blocked; it is never silently replaced.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">2 · Early-risk layer</span>
        <h2>ETF flow can permit a small BTC entry</h2>
        <p>Before the full trend state is active, the current overlay may authorize <strong>0.50× BTC exposure</strong> only when all required checks agree: the ETF-flow panel is causally available, at least two of the last three flow sessions are positive, their three-day sum is at least <strong>$500 million</strong>, BTC passes its <strong>10-day EMA</strong> filter, no hard risk invalidation is active and the <strong>15-day cooldown</strong> is clear.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">3 · Causal data</span>
        <h2>No future information</h2>
        <p>U.S. ETF-flow data is used under a strict <strong>D+1 contract</strong>: a U.S. session can affect only the following BTC UTC day. Weekends and exchange holidays may carry forward the last valid state. A missing expected trading session fails closed and blocks execution.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">4 · Full strategy gate</span>
        <h2>Candidate is not the same as a live position</h2>
        <p>The upstream model can rank a broader crypto universe, but a model candidate alone does not create a trade. Trend permission, data health, the approved execution target and the real wallet state must all agree. The dashboard reads real exposure from Hyperliquid, never from a model label.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">5 · Timing</span>
        <h2>Daily, after the market day closes</h2>
        <p>The Raspberry Pi is the only automatic production producer. One canonical timer refreshes data, builds the strategy snapshot, validates freshness and provenance, reconciles each eligible account, submits any required transition and publishes the final state. It does not chase intraday price moves.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">6 · Order safety</span>
        <h2>One execution path with restart protection</h2>
        <p>Position size is based on fresh account equity multiplied by the validated target exposure. Each order receives a deterministic client order ID and a durable journal entry before submission. After a restart, the worker checks the exchange before deciding whether any residual order is safe. Two competing live schedulers are forbidden.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">7 · Account permissions</span>
        <h2>Your agent can trade, not withdraw</h2>
        <p>The public website reads balances and performance. Live orders are sent only by the Pi using the separately authorized Hyperliquid agent for that account. The agent authorization does not expose a wallet seed phrase to TrendAtlas and does not grant withdrawal rights.</p>
      </article>

      <article className="strategy-card">
        <span className="metric-label">8 · Performance</span>
        <h2>Real exchange results, cash-flow adjusted</h2>
        <p>Balance, positions, fills, fees and funding come from Hyperliquid. Deposits and withdrawals are excluded from profit and loss. If the exchange history is incomplete, the return is shown as unavailable instead of being invented.</p>
      </article>
    </section>

    <section className="strategy-technical">
      <p className="eyebrow">Technical production facts</p>
      <h2>Current version and validation assumptions</h2>
      <dl className="strategy-facts strategy-facts--wide">
        <div><dt>Production model</dt><dd>ETF-flow impulse · early risk · 15-day cooldown</dd></div>
        <div><dt>Internal version</dt><dd>phase68g_etf_flow_impulse_early_risk_cooldown_15</dd></div>
        <div><dt>Fallback model</dt><dd>BTC persistence · 10-day EMA · early risk</dd></div>
        <div><dt>Benchmark</dt><dd>BTC</dd></div>
        <div><dt>Historical borrow assumption</dt><dd>12% annualized</dd></div>
        <div><dt>Historical transition slippage</dt><dd>10 basis points</dd></div>
      </dl>
      <p className="dashboard-note">Backtests and validation assumptions are not guarantees. Actual exchange fees, fills, slippage and funding can differ.</p>
    </section>

    <div className="strategy-actions"><Link className="button" href="/dashboard">Back to dashboard</Link></div>
  </main>;
}
