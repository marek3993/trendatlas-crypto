import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { calculateHyperliquidAccountPerformance, type PerformanceCalculationInput } from "@/lib/hyperliquid/performance";

const addressA = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const addressB = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const root = process.cwd();
const source = (relativePath: string) => fs.readFileSync(path.join(root, relativePath), "utf8");
const migration = source("supabase/migrations/202609040003_create_hyperliquid_account_performance.sql");
const dashboard = source("src/app/dashboard/page.tsx");
const performanceSource = source("src/lib/hyperliquid/performance.ts");
const refreshAction = source("src/app/dashboard/actions.ts");

function ms(day: string): number {
  return Date.parse(`${day}T00:00:00.000Z`);
}

function input(overrides: Partial<PerformanceCalculationInput> = {}): PerformanceCalculationInput {
  const asOfMs = ms("2026-09-03") + 12 * 60 * 60 * 1000;
  return {
    address: addressA,
    asOfMs,
    snapshot: { address: addressA, accountEquityUsd: 100, withdrawableUsd: 100, positions: [], openOrderCount: 0 },
    portfolio: [["allTime", { accountValueHistory: [[ms("2026-09-01"), "100"], [ms("2026-09-02"), "100"]] }]],
    fills: [],
    funding: [],
    nonFundingLedgerUpdates: [],
    ...overrides
  };
}

describe("per-user real account performance", () => {
  it("derives a result from the connected user's own normalized master address only", () => {
    const result = calculateHyperliquidAccountPerformance(input({ address: addressA }));
    expect(result.address).toBe(addressA);
    expect(result.address).not.toBe(addressB);
    expect(refreshAction).toContain('.eq("user_id", user.id)');
    expect(refreshAction).toContain("getHyperliquidAccountPerformance(account.master_address)");
  });

  it("excludes a deposit from live PnL", () => {
    const result = calculateHyperliquidAccountPerformance(input({
      snapshot: { address: addressA, accountEquityUsd: 200, withdrawableUsd: 200, positions: [], openOrderCount: 0 },
      nonFundingLedgerUpdates: [{ time: ms("2026-09-02"), delta: { type: "deposit", usdc: "100" } }]
    }));
    expect(result.totalLivePnlUsd).toBe(0);
    expect(result.breakdown?.depositsUsd).toBe(100);
  });

  it("excludes a withdrawal from live PnL", () => {
    const result = calculateHyperliquidAccountPerformance(input({
      snapshot: { address: addressA, accountEquityUsd: 50, withdrawableUsd: 50, positions: [], openOrderCount: 0 },
      nonFundingLedgerUpdates: [{ time: ms("2026-09-02"), delta: { type: "withdraw", usdc: "50" } }]
    }));
    expect(result.totalLivePnlUsd).toBe(0);
    expect(result.breakdown?.withdrawalsUsd).toBe(50);
  });

  it("calculates all-time PnL from an opening deposit before portfolio history", () => {
    const result = calculateHyperliquidAccountPerformance(input({
      snapshot: {
        address: addressA,
        accountEquityUsd: 83.186462,
        withdrawableUsd: 83.186462,
        positions: [],
        openOrderCount: 0
      },
      portfolio: [["allTime", {
        accountValueHistory: [
          [ms("2026-04-08"), "9.94"],
          [ms("2026-09-03"), "83.186462"]
        ]
      }]],
      nonFundingLedgerUpdates: [
        { time: ms("2026-04-05"), delta: { type: "send", user: addressB, destination: addressA, amount: "9.94", usdcValue: "9.94" } },
        { time: ms("2026-05-11"), delta: { type: "deposit", usdc: "29.64" } },
        { time: ms("2026-09-02"), delta: { type: "send", user: addressB, destination: addressA, amount: "42.6", usdcValue: "42.6" } }
      ]
    }));

    expect(result.totalLivePnlUsd).toBe(1.006462);
    expect(result.breakdown?.depositsUsd).toBe(82.18);
    expect(result.liveGenesisAtMs).toBe(ms("2026-04-05"));
    expect(result.cashFlowAdjustedReturnAvailable).toBe(false);
  });

  it("includes fees and funding in the independent breakdown", () => {
    const result = calculateHyperliquidAccountPerformance(input({
      snapshot: { address: addressA, accountEquityUsd: 109.4, withdrawableUsd: 109.4, positions: [], openOrderCount: 0 },
      fills: [{ time: ms("2026-09-02"), closedPnl: "10", fee: "0.5" }],
      funding: [{ time: ms("2026-09-02"), usdc: "-0.1" }]
    }));
    expect(result.breakdown?.tradingPnlUsd).toBe(10);
    expect(result.breakdown?.feesUsd).toBe(-0.5);
    expect(result.breakdown?.fundingUsd).toBe(-0.1);
    expect(result.totalLivePnlUsd).toBe(9.4);
  });

  it("marks 30 and 90 days unavailable when live history is insufficient", () => {
    const result = calculateHyperliquidAccountPerformance(input());
    expect(result.windows["30d"]).toMatchObject({ available: false, reason: "insufficient_live_history" });
    expect(result.windows["90d"]).toMatchObject({ available: false, reason: "insufficient_live_history" });
  });

  it("uses database RLS and the account-owner foreign key for both current and history rows", () => {
    expect(migration).toContain("enable row level security");
    expect(migration).toContain("force row level security");
    expect(migration).toContain("hyperliquid_account_performance_owner_fk");
    expect(migration).toContain("hyperliquid_account_performance_history_owner_fk");
    expect(migration).toContain("hyperliquid_account_performance_select_own");
    expect(migration).toContain("hyperliquid_account_performance_history_select_own");
    expect(migration.match(/auth\.uid\(\)\) = user_id/g)?.length).toBeGreaterThanOrEqual(6);
    expect(migration).toContain("unique (hyperliquid_account_id, performance_day)");
  });

  it("has no model or production snapshot fallback and no order capability", () => {
    expect(performanceSource).not.toMatch(/model|paper|outputs\/|data\/|run_trendatlas_production/i);
    expect(dashboard).not.toMatch(/model|paper|outputs\/|data\/|run_trendatlas_production/i);
    expect(performanceSource).not.toMatch(/marketOrder|limitOrder|submitOrder|cancelOrder|transfer\s*\(|withdraw\s*\(|updateLeverage/i);
  });
});
