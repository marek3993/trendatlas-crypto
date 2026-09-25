import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { normalizeHyperliquidAddress, validateHyperliquidAddress } from "@/lib/hyperliquid/address";
import { getHyperliquidAccountSnapshot } from "@/lib/hyperliquid/info";

const webRoot = process.cwd();
const repositoryRoot = path.resolve(webRoot, "..");
const source = (relativePath: string) => fs.readFileSync(path.join(webRoot, relativePath), "utf8");
const migration = source("supabase/migrations/202609040002_create_hyperliquid_accounts.sql");
const infoClient = source("src/lib/hyperliquid/info.ts");
const onboardingAction = source("src/app/onboarding/actions.ts");
const dashboard = source("src/app/dashboard/page.tsx");
const connectForm = source("src/components/hyperliquid-connect-form.tsx");

function filesUnder(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(target) : [target];
  });
}

describe("Hyperliquid read-only onboarding", () => {
  it.each([{ coin: "BTC", szi: "bad" }, { coin: "BTC", szi: "" }, { szi: "0.1" }, { coin: "BTC" }])("rejects malformed position rows instead of inventing CASH: %j", async (position) => {
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init: RequestInit) => {
      const request = JSON.parse(String(init.body)) as { type: string };
      const responses: Record<string, unknown> = {
        userAbstraction: "unifiedAccount",
        clearinghouseState: { marginSummary: { accountValue: "100", totalMarginUsed: "0" }, assetPositions: [{ position }] },
        spotClearinghouseState: { balances: [{ coin: "USDC", total: "100", hold: "0" }] }, openOrders: []
      };
      return new Response(JSON.stringify(responses[request.type]));
    }));
    try { await expect(getHyperliquidAccountSnapshot("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")).rejects.toThrow("account data is unavailable"); } finally { vi.unstubAllGlobals(); }
  });
  it("uses unified native balances without double-counting meaningless perps equity", async () => {
    const fetcher = vi.fn(async (_url: unknown, init: RequestInit) => {
      const request = JSON.parse(String(init.body)) as { type: string };
      const responses: Record<string, unknown> = {
        userAbstraction: "unifiedAccount",
        clearinghouseState: { marginSummary: { accountValue: "19.63", totalMarginUsed: "20.18" }, withdrawable: "0", assetPositions: [{ position: { coin: "BTC", szi: "0.0004", entryPx: "100000" } }] },
        spotClearinghouseState: { balances: [{ coin: "USDC", total: "82.08", hold: "20.18" }, { coin: "USDH", total: "2", hold: "0" }, { coin: "USDE", total: "3", hold: "0" }, { coin: "USDT0", total: "4", hold: "0" }] },
        openOrders: [{ coin: "AVAX", oid: 77, side: "A", sz: "1.2" }]
      };
      return new Response(JSON.stringify(responses[request.type]));
    });
    vi.stubGlobal("fetch", fetcher);
    try {
      const snapshot = await getHyperliquidAccountSnapshot("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
      expect(snapshot.accountEquityUsd).toBeCloseTo(91.08);
      expect(snapshot.marginAvailableUsd).toBeCloseTo(61.9);
      expect(snapshot.withdrawableUsd).toBeNull();
      expect(snapshot.openOrders).toEqual([{ asset: "AVAX", orderId: "77", side: "sell", size: 1.2 }]);
      expect(fetcher.mock.calls.every(([, request]) => !String(request.body).includes('"type":"order"'))).toBe(true);
    } finally { vi.unstubAllGlobals(); }
  });
  it("accepts and normalizes a valid Hyperliquid address", () => {
    const input = "  0xAbCdEf0123456789aBCdEf0123456789aBcDeF01  ";
    expect(validateHyperliquidAddress(input)).toEqual({ ok: true, address: "0xabcdef0123456789abcdef0123456789abcdef01" });
    expect(normalizeHyperliquidAddress(input)).toBe("0xabcdef0123456789abcdef0123456789abcdef01");
  });

  it("rejects an invalid Hyperliquid address", () => {
    expect(validateHyperliquidAddress("0x1234")).toMatchObject({ ok: false });
    expect(validateHyperliquidAddress("not-an-address")).toMatchObject({ ok: false });
  });

  it("creates a read-only connection for the authenticated owner only", () => {
    expect(onboardingAction).toContain("const { user } = await requireUser()");
    expect(onboardingAction).toContain("user_id: user.id");
    expect(onboardingAction).toContain('connection_status: "read_only_connected"');
    expect(onboardingAction).toContain("verified_at:");
  });

  it("enforces cross-user RLS denial for every table operation", () => {
    expect(migration).toContain("enable row level security");
    expect(migration).toContain("force row level security");
    expect(migration).toContain("hyperliquid_accounts_select_own");
    expect(migration).toContain("hyperliquid_accounts_insert_own");
    expect(migration).toContain("hyperliquid_accounts_update_own");
    expect(migration).toContain("hyperliquid_accounts_delete_own");
    expect(migration.match(/auth\.uid\(\)\) = user_id/g)?.length).toBeGreaterThanOrEqual(5);
  });

  it("permits only the documented read-only account and performance Info request types", () => {
    expect(infoClient).toContain('"clearinghouseState"');
    expect(infoClient).toContain('"openOrders"');
    expect(infoClient).toContain('"portfolio"');
    expect(infoClient).toContain('"userFillsByTime"');
    expect(infoClient).toContain('"userFunding"');
    expect(infoClient).toContain('"userNonFundingLedgerUpdates"');
    expect(infoClient).toContain('"extraAgents"');
    expect(infoClient).not.toMatch(/"(exchange|order|cancel|transfer|withdraw|updateLeverage)"/i);
    expect(infoClient).toContain('method: "POST"');
    expect(infoClient).toContain("https://api.hyperliquid.xyz/info");
    expect(infoClient).toContain("withdrawableUsd");
    expect(infoClient).not.toContain("freeCollateralUsd");
  });

  it("includes spot USDC in combined equity and withdrawable balances", () => {
    expect(infoClient).toContain('"spotClearinghouseState"');
    expect(infoClient).toContain('requestInfo<SpotClearinghouseState>("spotClearinghouseState", validation.address)');
    expect(infoClient).toContain('spotState.balances.find(({ coin }) => coin === "USDC")');
    expect(infoClient).toContain("perpsAccountEquityUsd + spotUsdcUsd");
    expect(infoClient).toContain("perpsWithdrawableUsd + spotUsdcUsd");
  });

  it("revalidates a named trading agent and its exchange expiry", () => {
    expect(infoClient).toContain("getHyperliquidAgentAuthorization");
    expect(infoClient).toContain('requestInfo<Array<{ address?: unknown; name?: unknown; validUntil?: unknown }>>');
    expect(infoClient).toContain("validUntilMs");
  });

  it("fails closed before network access for an unknown Info request", () => {
    const guard = infoClient.indexOf("if (!isAllowedInfoRequestType(type)) throw new HyperliquidInfoError()");
    const request = infoClient.indexOf("response = await fetch");
    expect(guard).toBeGreaterThanOrEqual(0);
    expect(request).toBeGreaterThan(guard);
  });

  it("has no secret fields in the connection schema", () => {
    expect(migration).not.toMatch(/private|signer|secret|seed|trading_enabled/i);
  });

  it("has no secret input in the connection UI", () => {
    expect(connectForm).toContain('name="masterAddress"');
    expect(connectForm).not.toMatch(/password|private|seed|secret|signer/i);
  });

  it("does not import a Hyperliquid trading SDK", () => {
    const appSource = filesUnder(path.join(webRoot, "src")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    expect(appSource).not.toMatch(/from\s+["'][^"']*(hyperliquid-sdk|hyperliquid.*exchange|nktkas)[^"']*["']/i);
    expect(appSource).not.toMatch(/require\(["'][^"']*(hyperliquid-sdk|hyperliquid.*exchange|nktkas)[^"']*["']\)/i);
  });

  it("does not expose an order submitter or cancellation from browser routes", () => {
    const appSource = filesUnder(path.join(webRoot, "src", "app")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    expect(appSource).not.toMatch(/marketOrder|limitOrder|submitOrder|cancelOrder|modifyOrder|transfer\s*\(|withdraw\s*\(|updateLeverage/i);
  });

  it("requires authentication for onboarding", () => {
    expect(source("src/app/onboarding/page.tsx")).toContain("await requireUser()");
    expect(source("src/proxy.ts")).toContain('"/onboarding"');
  });

  it("queries the dashboard with the logged-in user's account only", () => {
    expect(dashboard).toContain("const { supabase, user } = await requireUser()");
    expect(dashboard).toContain('.eq("user_id", user.id)');
    expect(dashboard).toContain("getHyperliquidAccountPerformance(account.master_address)");
  });

  it("gives every authenticated account the complete responsive dashboard structure", () => {
    expect(dashboard).toContain('className="dashboard-shell"');
    expect(dashboard).toContain("Status and controls");
    expect(dashboard).toContain("Wallet snapshot");
    expect(dashboard).toContain("Real account performance");
    expect(dashboard).toContain("performance.snapshot.positions");
    expect(dashboard).toContain("performance.snapshot.openOrderCount");
    expect(dashboard).toContain('TRENDATLAS_MULTI_ACCOUNT_EXECUTOR_AVAILABLE === "true"');
    expect(dashboard).toContain("automaticTradingLabel");
    expect(dashboard).toContain("Last evaluated strategy target");
    expect(dashboard).toContain("Real wallet position");
    expect(dashboard).toContain("Last execution result");
  });

  it("disconnects only the logged-in user's connection", () => {
    expect(onboardingAction).toContain('delete().eq("user_id", user.id)');
    expect(onboardingAction).not.toMatch(/formData\.get\([^)]*(id|user)/i);
  });

  it("does not copy the protected production address into web source", () => {
    const production = fs.readFileSync(path.join(repositoryRoot, "scripts/execution/run_trendatlas_production.py"), "utf8");
    const addresses = production.match(/0x[a-fA-F0-9]{40}/g) ?? [];
    const appSource = filesUnder(path.join(webRoot, "src")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    addresses.forEach((address) => expect(appSource).not.toContain(address));
  });

  it("keeps read-only browser code isolated from the approved production cutover", () => {
    const production = fs.readFileSync(path.join(repositoryRoot, "scripts/execution/run_trendatlas_production.py"), "utf8");
    const appSource = filesUnder(path.join(webRoot, "src", "app")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    expect(production).toContain("run_multi_account_backend");
    expect(appSource).not.toContain("run_multi_account_backend");
  });
});
