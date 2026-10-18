import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { privateKeyToAccount } from "viem/accounts";
import { createEnvironmentAgentSecretProtector } from "@/lib/hyperliquid/agent-authorization";
import { MultiAccountExecutor, isEligibleMultiAccount, type ExchangeGateway, type ExecutionRepository, type JournalAction, type ExchangeOrder, type KnownOrder } from "@/server/multi-account-executor/engine";
import { buildPlan } from "@/server/multi-account-executor/planner";
import { deterministicCloid } from "@/server/multi-account-executor/cloid";
import { HyperliquidDryRunGateway, fetchHyperliquidMarketIndex } from "@/server/multi-account-executor/dry-run-gateway";
import { HyperliquidOrderRejectedError } from "@/server/multi-account-executor/hyperliquid-live-gateway";
import { preflightMultiAccountCandidates } from "@/server/multi-account-executor/live-preflight";
import type { AccountState, AuthorizedTarget, EligibleAccount, MarketSpec, PlannedAction } from "@/server/multi-account-executor/types";

const privateKey = `0x${"11".repeat(32)}` as const;
const agentAddress = privateKeyToAccount(privateKey).address.toLowerCase();
const masterAddress = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const target = (asset: string, exposure = asset === "CASH" ? 0 : 1): AuthorizedTarget => ({ strategyVersion: "v1", closedDay: "2026-09-25", signalId: `signal-${asset}`, asset, exposure, stale: false, executionGate: "approved" });
const market = (asset: string, markPrice = 100): MarketSpec => ({ asset, markPrice, minNotionalUsd: 10, sizeDecimals: 5, maxLeverage: 10 });
const markets = new Map(["BTC", "ETH", "AVAX", "SOL", "NOVEL"].map((asset) => [asset, market(asset)]));
const account = (positions: AccountState["positions"] = [], equityUsd = 100): AccountState => ({ equityUsd, positions, openOrderCount: 0, openOrders: [], marginAvailableUsd: 100 });
const candidate = (overrides: Partial<EligibleAccount> = {}): EligibleAccount => ({ userId: "u", accountId: "account-a", masterAddress, agentAddress, agentName: "TA-1234abcd", authorizationId: "authorization-a", connectionStatus: "read_only_connected", authorizationStatus: "authorized", ownershipVerifiedAt: "2026-09-01", agentAuthorizedAt: "2026-09-01", autoTradingRequested: true, executionStatus: "ready", hasEncryptedSecret: true, ...overrides });
const position = (asset: string, size = 0.49) => ({ asset, size, markPrice: 100 });
const originalKek = process.env.TRENDATLAS_AGENT_KEK_B64;
beforeEach(() => { process.env.TRENDATLAS_AGENT_KEK_B64 = Buffer.alloc(32, 11).toString("base64"); });
afterEach(() => { vi.restoreAllMocks(); if (originalKek === undefined) delete process.env.TRENDATLAS_AGENT_KEK_B64; else process.env.TRENDATLAS_AGENT_KEK_B64 = originalKek; });

function harness(initial = account(), targetMarkets = markets) {
  let state = structuredClone(initial);
  const journal = new Map<string, JournalAction>();
  const known = new Map<string, KnownOrder>();
  const events: string[] = [];
  const orders: ExchangeOrder[] = [];
  const encryptedSecret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).encrypt(privateKey);
  const repository: ExecutionRepository = {
    listMultiAccountCandidates: async () => [{ ...candidate(), encryptedSecret }],
    tryAcquire: async () => true,
    renewLease: async () => true,
    release: async () => undefined,
    reserveNonce: async () => BigInt(Date.now()),
    createRun: async () => "run",
    readActions: async () => [...journal.values()].filter(({ runId }) => !runId || runId === "run"),
    readUnresolvedActions: async () => [],
    markActionVerified: async () => undefined,
    isManagedOrder: async () => true,
    recordAction: async (runId, action, cloid, submission, orderId, expiresAtMs) => {
      events.push(`journal:${action.action}:${submission}`);
      const old = journal.get(cloid);
      if (old && submission === "NOT_SUBMITTED" && old.state !== "NOT_SUBMITTED") return;
      if (old?.expiresAtMs && expiresAtMs !== undefined && old.expiresAtMs !== expiresAtMs) throw new Error("immutable expiry");
      journal.set(cloid, { action, cloid, state: submission, orderId: orderId ?? old?.orderId, runId, expiresAtMs: expiresAtMs ?? old?.expiresAtMs });
    },
    finishRun: async () => undefined,
    setAccountStatus: async () => undefined
  };
  const exchange: ExchangeGateway = {
    readAccount: async () => { events.push("read"); return structuredClone(state); },
    readMarkets: async () => new Map(targetMarkets),
    userRole: async () => ({ role: "agent", user: masterAddress }),
    agentAuthorization: async () => ({ authorized: true, validUntilMs: Date.parse("2100-01-01") }),
    findByCloid: async (_master, cloid) => { events.push("lookup"); return known.get(cloid) ?? null; },
    writeIoc: async (order) => {
      events.push(`write:${order.action}`);
      orders.push(order);
      const current = state.positions.find(({ asset }) => asset === order.asset);
      const change = order.side === "sell" ? -order.size : order.size;
      const size = (current?.size ?? 0) + change;
      state.positions = state.positions.filter(({ asset }) => asset !== order.asset);
      if (Math.abs(size) > 1e-10) state.positions.push(position(order.asset, size));
      known.set(order.cloid, { state: "filled", orderId: String(orders.length) });
      return { orderId: String(orders.length) };
    },
    cancelOrder: async (order) => {
      events.push("cancel");
      state.openOrders = state.openOrders?.filter(({ orderId }) => orderId !== order.orderId);
      state.openOrderCount = state.openOrders?.length ?? 0;
    }
  };
  return { repository, exchange, journal, known, events, orders, setState: (value: AccountState) => { state = value; }, state: () => state, run: (selected: AuthorizedTarget, mode: "live" | "dry_run" | "disabled" = "live") => new MultiAccountExecutor(repository, exchange, mode).runAllForTarget(selected) };
}

describe("dynamic exit-first production planner", () => {
  it.each(["AVAX", "NOVEL"])("plans cash to metadata-supported %s without source edits", (asset) => {
    expect(buildPlan(target(asset, 1.25), account(), markets).actions[0]).toMatchObject({ action: "ENTER", asset, requestedNotionalUsd: 125 });
  });
  it("reproduces BTC 0.49x to AVAX 1.25x", () => {
    expect(buildPlan(target("AVAX", 1.25), account([position("BTC")]), markets).actions).toMatchObject([
      { action: "EXIT", asset: "BTC", size: 0.49, reduceOnly: true, side: "sell" },
      { action: "ENTER", asset: "AVAX", size: 1.25, reduceOnly: false, side: "buy" }
    ]);
  });
  it.each([...[...markets.keys()].map((asset) => [asset, "CASH"]), ...[...markets.keys()].flatMap((from) => [...markets.keys()].map((to) => [from, to]))])("plans supported %s to %s", (from, to) => {
    expect(buildPlan(target(to), account([position(from)]), markets).state).not.toBe("BLOCKED");
  });
  it("keeps executable exits when entry metadata, minimum or precision is invalid", () => {
    for (const entryMarket of [undefined, { ...market("AVAX"), minNotionalUsd: 1000 }, { ...market("AVAX"), sizeDecimals: -1 }]) {
      const metadata = new Map(markets);
      if (entryMarket) metadata.set("AVAX", entryMarket); else metadata.delete("AVAX");
      expect(buildPlan(target("AVAX"), account([position("BTC")]), metadata)).toMatchObject({ state: "ROTATE", actions: [{ action: "EXIT", asset: "BTC" }], entryBlockedReason: expect.any(String) });
    }
  });
  it("plans every long and short exit for CASH without entry minimum", () => {
    expect(buildPlan(target("CASH"), account([position("BTC", -0.01), position("AVAX", 0.01)]), markets).actions).toMatchObject([
      { action: "EXIT", asset: "AVAX", side: "sell", reduceOnly: true }, { action: "EXIT", asset: "BTC", side: "buy", reduceOnly: true }
    ]);
  });
  it("invalid target cannot cause any exit", () => expect(buildPlan({ ...target("AVAX"), stale: true } as unknown as AuthorizedTarget, account([position("BTC")]), markets).actions).toEqual([]));
  it("margin only blocks increasing exposure", () => {
    const state = { ...account([position("BTC")]), marginAvailableUsd: 0 };
    expect(buildPlan(target("AVAX"), state, markets).actions[0].action).toBe("EXIT");
    expect(buildPlan(target("BTC", 0.1), state, markets).actions[0].reduceOnly).toBe(true);
    expect(buildPlan(target("AVAX"), { ...state, positions: [] }, markets).reason).toContain("margin");
  });
});

describe("execution state machine and recovery", () => {
  it.each([["BTC", "AVAX"], ["AVAX", "BTC"]])("executes %s to %s only after fresh exit read-back", async (from, to) => {
    const h = harness(account([position(from)]));
    expect(await h.run(target(to, 1.25))).toMatchObject([{ status: "FILLED_AND_ALIGNED", orderRequested: true }]);
    expect(h.orders.map(({ action, asset, reduceOnly }) => ({ action, asset, reduceOnly }))).toEqual([{ action: "EXIT", asset: from, reduceOnly: true }, { action: "ENTER", asset: to, reduceOnly: false }]);
    const exit = h.events.indexOf("write:EXIT");
    const entry = h.events.indexOf("write:ENTER");
    expect(h.events.slice(exit + 1, entry)).toContain("read");
    expect(h.state().positions).toEqual([position(to, 1.25)]);
  });
  it("resizes entry from fresh post-exit equity", async () => {
    const h = harness(account([position("BTC")]));
    const write = h.exchange.writeIoc;
    h.exchange.writeIoc = async (order) => { const response = await write(order); if (order.action === "EXIT") h.state().equityUsd = 80; return response; };
    await h.run(target("AVAX", 1.25));
    expect(h.orders[1].requestedNotionalUsd).toBe(100);
  });
  it("closes multiple non-target positions and a short before entry", async () => {
    const h = harness(account([position("BTC"), position("SOL", -0.3), position("ETH", 0.2)]));
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "FILLED_AND_ALIGNED" }]);
    expect(h.orders.map(({ action }) => action)).toEqual(["EXIT", "EXIT", "EXIT", "ENTER"]);
    expect(h.orders.find(({ asset }) => asset === "SOL")).toMatchObject({ side: "buy", reduceOnly: true });
  });
  it("CASH closes all positions", async () => {
    const h = harness(account([position("BTC"), position("AVAX", -0.2)]));
    expect(await h.run(target("CASH"))).toMatchObject([{ status: "FILLED_AND_ALIGNED" }]);
    expect(h.state().positions).toEqual([]);
    expect(h.orders.every(({ reduceOnly }) => reduceOnly)).toBe(true);
  });
  it("unsupported entry stays CASH after successful EXIT", async () => {
    const metadata = new Map(markets); metadata.delete("AVAX");
    const h = harness(account([position("BTC")]), metadata);
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "EXITED_ENTRY_FAILED_STAYING_CASH", orderRequested: true }]);
    expect(h.orders).toHaveLength(1);
    expect(h.state().positions).toEqual([]);
  });
  it("insufficient entry margin cannot prevent EXIT", async () => {
    const h = harness({ ...account([position("BTC")]), marginAvailableUsd: 0 });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "EXITED_ENTRY_FAILED_STAYING_CASH" }]);
    expect(h.orders.map(({ action }) => action)).toEqual(["EXIT"]);
  });
  it("a deterministic rejected entry stays CASH and does not roll back", async () => {
    const h = harness(account([position("BTC")]));
    const write = h.exchange.writeIoc;
    h.exchange.writeIoc = async (order) => { if (order.action === "ENTER") throw new HyperliquidOrderRejectedError(); return write(order); };
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "EXITED_ENTRY_FAILED_STAYING_CASH", failureKind: "deterministic" }]);
    expect(h.state().positions).toEqual([]);
  });
  it("partial EXIT never reaches ENTRY", async () => {
    const h = harness(account([position("BTC")]));
    h.exchange.writeIoc = async (order) => { h.orders.push(order); h.state().positions = [position("BTC", 0.1)]; return { orderId: "1" }; };
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "PARTIAL" }]);
    expect(h.orders).toHaveLength(1);
  });
  it("power loss between EXIT and ENTRY resumes only the missing entry", async () => {
    const h = harness(account());
    const action: PlannedAction = { action: "EXIT", asset: "BTC", side: "sell", size: 0.49, requestedNotionalUsd: 49, reduceOnly: true, leg: 0 };
    const cloid = `0x${"12".repeat(16)}`;
    h.journal.set(cloid, { action, cloid, state: "AMBIGUOUS", runId: "run" });
    h.known.set(cloid, { state: "filled", orderId: "old" });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "FILLED_AND_ALIGNED" }]);
    expect(h.orders.map(({ action }) => action)).toEqual(["ENTER"]);
  });
  it("previous signal ambiguity blocks new signal orders after account read-back", async () => {
    const h = harness(account());
    const action: PlannedAction = { action: "ENTER", asset: "BTC", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    h.repository.readUnresolvedActions = async () => [{ action, cloid: `0x${"34".repeat(16)}`, state: "AMBIGUOUS", runId: "previous-run" }];
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "UNKNOWN_SUBMISSION_STATE", orderRequested: null }]);
    expect(h.orders).toEqual([]);
    expect(h.events).toContain("lookup");
  });
  it("an open CLOID cannot be overruled by an empty open-orders snapshot", async () => {
    const h = harness(account());
    const action: PlannedAction = { action: "ENTER", asset: "BTC", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    const cloid = `0x${"56".repeat(16)}`;
    h.repository.readUnresolvedActions = async () => [{ action, cloid, state: "AMBIGUOUS", runId: "previous-run" }];
    h.known.set(cloid, { state: "open", orderId: "8" });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "UNKNOWN_SUBMISSION_STATE" }]);
    expect(h.orders).toEqual([]);
  });
  it("an apparently aligned account cannot hide an unresolved older request", async () => {
    const h = harness(account([position("AVAX", 1)]));
    const action: PlannedAction = { action: "ENTER", asset: "BTC", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    h.repository.readUnresolvedActions = async () => [{ action, cloid: `0x${"78".repeat(16)}`, state: "AMBIGUOUS", runId: "previous-run" }];
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "UNKNOWN_SUBMISSION_STATE" }]);
    expect(h.orders).toEqual([]);
  });
  it("recovers a proven expired absent request with a new residual CLOID", async () => {
    const h = harness(account());
    const action: PlannedAction = { action: "ENTER", asset: "AVAX", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    const cloid = `0x${"90".repeat(16)}`;
    h.journal.set(cloid, { action, cloid, state: "AMBIGUOUS", expiresAtMs: Date.now() - 31_000 });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "FILLED_AND_ALIGNED" }]);
    expect(h.orders).toHaveLength(1);
    expect(h.orders[0].cloid).not.toBe(cloid);
    expect(h.journal.get(h.orders[0].cloid)?.expiresAtMs).toBe(h.orders[0].expiresAtMs);
  });
  it("cannot recover an absent request before its durable expiry and skew allowance", async () => {
    const h = harness(account());
    const action: PlannedAction = { action: "ENTER", asset: "AVAX", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    const cloid = `0x${"91".repeat(16)}`;
    h.journal.set(cloid, { action, cloid, state: "AMBIGUOUS", expiresAtMs: Date.now() - 10_000 });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "UNKNOWN_SUBMISSION_STATE" }]);
    expect(h.orders).toEqual([]);
  });
  it("expired evidence still cannot override transport ambiguity", async () => {
    const h = harness(account());
    const action: PlannedAction = { action: "ENTER", asset: "AVAX", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    const cloid = `0x${"92".repeat(16)}`;
    h.journal.set(cloid, { action, cloid, state: "AMBIGUOUS", expiresAtMs: Date.now() - 60_000 });
    h.known.set(cloid, { state: "unknown" });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "UNKNOWN_SUBMISSION_STATE" }]);
    expect(h.orders).toEqual([]);
  });
  it("repeated signal or publish failure never duplicates a filled order", async () => {
    const h = harness();
    await h.run(target("AVAX"));
    await h.run(target("AVAX"));
    expect(h.orders).toHaveLength(1);
  });
  it("writes the durable ambiguous boundary before sending and never blind retries", async () => {
    const h = harness();
    h.exchange.writeIoc = async () => { h.events.push("write-timeout"); throw new Error("timeout"); };
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "UNKNOWN_SUBMISSION_STATE" }]);
    expect(h.events.indexOf("journal:ENTER:AMBIGUOUS")).toBeLessThan(h.events.indexOf("write-timeout"));
    await h.run(target("AVAX"));
    expect(h.events.filter((event) => event === "write-timeout")).toHaveLength(1);
  });
  it("reconciles a journal-owned conflicting open order before trading", async () => {
    const h = harness({ ...account([position("BTC")]), openOrderCount: 1, openOrders: [{ asset: "BTC", orderId: "123", size: 0.1, side: "buy" }] });
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "FILLED_AND_ALIGNED" }]);
    expect(h.events.indexOf("cancel")).toBeLessThan(h.events.indexOf("write:EXIT"));
    expect(h.state().openOrderCount).toBe(0);
  });
  it("never cancels an unowned order", async () => {
    const h = harness({ ...account(), openOrderCount: 1, openOrders: [{ asset: "BTC", orderId: "123" }] });
    h.repository.isManagedOrder = async () => false;
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "BLOCKED" }]);
    expect(h.events).not.toContain("cancel");
  });
  it("dry-run never cancels, queries order state or writes", async () => {
    const h = harness();
    expect(await h.run(target("AVAX"), "dry_run")).toMatchObject([{ status: "DRY_RUN", orderRequested: false }]);
    expect(h.events).not.toContain("lookup");
    expect(h.orders).toEqual([]);
    const gateway = new HyperliquidDryRunGateway();
    await expect(gateway.cancelOrder({} as never)).rejects.toThrow("cannot cancel");
  });
  it("temporary blocked/error accounts remain eligible next day", () => {
    expect(isEligibleMultiAccount(candidate({ executionStatus: "blocked" }))).toBe(true);
    expect(isEligibleMultiAccount(candidate({ executionStatus: "error" }))).toBe(true);
    expect(isEligibleMultiAccount(candidate({ autoTradingRequested: false }))).toBe(false);
    expect(isEligibleMultiAccount(candidate({ hasEncryptedSecret: false }))).toBe(false);
  });
  it("a failed account does not stop later sequential accounts", async () => {
    const h = harness();
    const encryptedSecret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).encrypt(privateKey);
    h.repository.listMultiAccountCandidates = async () => [{ ...candidate({ accountId: "broken", agentAddress: "bad" }), encryptedSecret }, { ...candidate(), encryptedSecret }];
    const role = h.exchange.userRole;
    h.exchange.userRole = async (agent) => { if (agent === "bad") throw new Error("offline"); return role(agent); };
    expect(await h.run(target("AVAX"))).toMatchObject([{ accountId: "broken", status: "FAILED" }, { accountId: "account-a", status: "FILLED_AND_ALIGNED" }]);
  });
  it("lost distributed lease prevents any write", async () => {
    const h = harness(); h.repository.renewLease = async () => false;
    expect(await h.run(target("AVAX"))).toMatchObject([{ status: "FAILED" }]);
    expect(h.orders).toEqual([]);
  });
});

describe("dynamic metadata and durable identity", () => {
  it("no-submit preflight finds unresolved older orders even on an aligned wallet", async () => {
    const h = harness(account([position("AVAX", 1)]));
    const action: PlannedAction = { action: "ENTER", asset: "BTC", side: "buy", size: 1, requestedNotionalUsd: 100, reduceOnly: false, leg: 0 };
    h.repository.readUnresolvedActions = async () => [{ action, cloid: `0x${"94".repeat(16)}`, state: "AMBIGUOUS", runId: "older" }];
    const results = await preflightMultiAccountCandidates(await h.repository.listMultiAccountCandidates(), target("AVAX"), h.exchange, h.repository);
    expect(results).toMatchObject([{ status: "FAILED", failureKind: "retryable" }]);
    expect(h.orders).toEqual([]);
    expect(h.events).not.toContain("cancel");
  });
  it("flat unsupported entry is distinct from an invalid strategy target in preflight", async () => {
    const metadata = new Map(markets); metadata.delete("AVAX");
    const h = harness(account(), metadata);
    const candidates = await h.repository.listMultiAccountCandidates();
    expect(await preflightMultiAccountCandidates(candidates, target("AVAX"), h.exchange, h.repository)).toMatchObject([{ status: "ENTRY_BLOCKED", entryBlockedReason: "target market metadata is unavailable" }]);
    expect(await preflightMultiAccountCandidates(candidates, { ...target("AVAX"), stale: true } as unknown as AuthorizedTarget, h.exchange, h.repository)).toMatchObject([{ status: "BLOCKED", reason: "strategy target is invalid" }]);
  });
  it("dry-run CLOID verification uses only the Info endpoint", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ status: "order", order: { status: "filled", order: { oid: 94 } } })));
    const gateway = new HyperliquidDryRunGateway(fetcher as typeof fetch);
    expect(await gateway.findByCloid(masterAddress, `0x${"94".repeat(16)}`)).toEqual({ state: "filled", orderId: "94" });
    expect(fetcher).toHaveBeenCalledWith("https://api.hyperliquid.xyz/info", expect.objectContaining({ body: expect.stringContaining('"type":"orderStatus"') }));
  });
  it("loads every currently supported market without a fixed symbol requirement", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify([{ universe: [{ name: "newCOIN", szDecimals: 3, maxLeverage: 8 }] }, [{ markPx: "12" }]])));
    expect([...(await fetchHyperliquidMarketIndex(fetcher as typeof fetch)).keys()]).toEqual(["NEWCOIN"]);
  });
  it("asset and side survive changed leg numbers after restart", () => {
    const identity = { userId: "u", accountId: "a", signalId: "s", closedDay: "2026-09-25", target: "AVAX", action: "ENTER", asset: "AVAX", side: "buy", leg: 1, attempt: 0 };
    expect(deterministicCloid(identity)).toBe(deterministicCloid({ ...identity, leg: 0 }));
    expect(deterministicCloid(identity)).not.toBe(deterministicCloid({ ...identity, asset: "BTC" }));
  });
  it("active planner and gateway contain no manual trading asset lists", () => {
    for (const filename of ["types.ts", "planner.ts", "dry-run-gateway.ts", "engine.ts"]) {
      const source = fs.readFileSync(path.join(process.cwd(), "src/server/multi-account-executor", filename), "utf8");
      expect(source).not.toMatch(/SUPPORTED_TARGETS|MANAGED_ASSETS|const MANAGED|\["BTC",\s*"ETH"\]/);
    }
  });
});
