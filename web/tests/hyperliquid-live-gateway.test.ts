import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { recoverTypedDataAddress, zeroAddress, type Hex } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { createEnvironmentAgentSecretProtector } from "@/lib/hyperliquid/agent-authorization";
import { MultiAccountExecutor, type ExchangeGateway, type ExchangeOrder, type ExecutionRepository } from "@/server/multi-account-executor/engine";
import { HyperliquidLiveGateway, normalizeHyperliquidOrderStatus } from "@/server/multi-account-executor/hyperliquid-live-gateway";
import {
  buildSignedHyperliquidIocPayload,
  computeHyperliquidIocLimitPrice,
  hyperliquidActionHash
} from "@/server/multi-account-executor/hyperliquid-l1-signing";
import { preflightMultiAccountCandidates } from "@/server/multi-account-executor/live-preflight";
import type { AccountState, AuthorizedTarget, EligibleAccount, MarketSpec } from "@/server/multi-account-executor/types";

const privateKey = `0x${"11".repeat(32)}` as Hex;
const agentAddress = privateKeyToAccount(privateKey).address.toLowerCase();
const masterAddress = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const cloid = `0x${"ab".repeat(16)}`;
const nonce = 1_770_000_000_000n;

function exchangeOrder(overrides: Partial<ExchangeOrder> = {}): ExchangeOrder {
  return {
    action: "ENTER",
    asset: "ETH",
    requestedNotionalUsd: 25,
    size: 0.01,
    reduceOnly: false,
    leg: 0,
    cloid,
    nonce,
    masterAddress,
    agentAddress,
    agentPrivateKey: privateKey,
    ...overrides
  };
}

afterEach(() => vi.restoreAllMocks());

describe("Hyperliquid L1 IOC signing", () => {
  it("matches the fixed MessagePack action-hash regression vector", () => {
    const action = {
      type: "order" as const,
      orders: [{
        a: 1,
        b: true,
        p: "2525",
        s: "0.01",
        r: false,
        t: { limit: { tif: "Ioc" as const } },
        c: cloid
      }] as const,
      grouping: "na" as const
    };
    expect(hyperliquidActionHash(action, nonce, nonce + 180_000n))
      .toBe("0xc0f627b74fadc2a12d466164f987e76754ab5ad594130786498f7cf01ce446e1");
  });

  it("builds an IOC-only payload whose signature recovers the expected agent", async () => {
    const payload = await buildSignedHyperliquidIocPayload(
      exchangeOrder(),
      { assetIndex: 1, markPrice: 2_500, sizeDecimals: 4 },
      Number(nonce)
    );
    const connectionId = hyperliquidActionHash(payload.action, nonce, BigInt(payload.expiresAfter));
    const recovered = await recoverTypedDataAddress({
      domain: { chainId: 1337, name: "Exchange", verifyingContract: zeroAddress, version: "1" },
      types: { Agent: [{ name: "source", type: "string" }, { name: "connectionId", type: "bytes32" }] },
      primaryType: "Agent",
      message: { source: "a", connectionId },
      signature: `${payload.signature.r}${payload.signature.s.slice(2)}${payload.signature.v.toString(16)}` as Hex
    });

    expect(payload.action).toEqual({
      type: "order",
      orders: [{ a: 1, b: true, p: "2525", s: "0.01", r: false, t: { limit: { tif: "Ioc" } }, c: cloid }],
      grouping: "na"
    });
    expect(recovered.toLowerCase()).toBe(agentAddress);
    expect(payload.expiresAfter).toBe(Number(nonce + 180_000n));
  });

  it("uses aggressive buy and sell limits while rejecting a stale nonce", async () => {
    expect(computeHyperliquidIocLimitPrice(2_500, true, 4)).toBe(2_525);
    expect(computeHyperliquidIocLimitPrice(2_500, false, 4)).toBe(2_475);
    await expect(buildSignedHyperliquidIocPayload(
      exchangeOrder(),
      { assetIndex: 1, markPrice: 2_500, sizeDecimals: 4 },
      Number(nonce + 31_000n)
    )).rejects.toThrow("failed safely");
  });

  it("rejects a private key that does not match the authorized agent", async () => {
    await expect(buildSignedHyperliquidIocPayload(
      exchangeOrder({ agentAddress: "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }),
      { assetIndex: 1, markPrice: 2_500, sizeDecimals: 4 },
      Number(nonce)
    )).rejects.toThrow("failed safely");
  });
});

describe("Hyperliquid live gateway transport", () => {
  it("normalizes CLOID status without treating transport ambiguity as absence", () => {
    expect(normalizeHyperliquidOrderStatus({ status: "unknownOid" })).toBeNull();
    expect(normalizeHyperliquidOrderStatus({ status: "open", order: { oid: 1 } })).toEqual({ state: "open", orderId: "1" });
    expect(normalizeHyperliquidOrderStatus({ status: "filled", order: { oid: 2 } })).toEqual({ state: "filled", orderId: "2" });
    expect(normalizeHyperliquidOrderStatus([{ status: "filled", order: { oid: 2 } }])).toEqual({ state: "filled", orderId: "2" });
    expect(normalizeHyperliquidOrderStatus({ status: "iocCanceled", order: { oid: 3 } })).toEqual({ state: "rejected", orderId: "3" });
    expect(normalizeHyperliquidOrderStatus({ unexpected: true })).toEqual({ state: "unknown", orderId: undefined });
  });

  it("submits exactly one signed order action and never serializes the private key", async () => {
    const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      void init;
      if (String(url).endsWith("/info")) {
        return new Response(JSON.stringify([
          { universe: [{ name: "BTC", szDecimals: 5 }, { name: "ETH", szDecimals: 4 }] },
          [{ markPx: "60000" }, { markPx: "2500" }]
        ]), { status: 200 });
      }
      return new Response(JSON.stringify({
        status: "ok",
        response: { type: "order", data: { statuses: [{ filled: { oid: 123, totalSz: "0.01", avgPx: "2525" } }] } }
      }), { status: 200 });
    });
    const gateway = new HyperliquidLiveGateway(fetcher as typeof fetch);
    vi.spyOn(Date, "now").mockReturnValue(Number(nonce));

    await expect(gateway.writeIoc(exchangeOrder())).resolves.toEqual({ orderId: "123" });
    expect(fetcher).toHaveBeenCalledTimes(2);
    const exchangeInit = fetcher.mock.calls[1][1] as RequestInit;
    const serialized = String(exchangeInit.body);
    const body = JSON.parse(serialized) as { action: { type: string; orders: Array<{ t: unknown }> } };
    expect(body.action.type).toBe("order");
    expect(body.action.orders).toHaveLength(1);
    expect(body.action.orders[0].t).toEqual({ limit: { tif: "Ioc" } });
    expect(serialized).not.toContain(privateKey);
    expect(serialized).not.toMatch(/withdraw|transfer|approveAgent|updateLeverage/i);
  });

  it("returns unknown on a CLOID transport failure so the engine cannot blind-submit", async () => {
    const gateway = new HyperliquidLiveGateway(vi.fn(async () => { throw new Error("offline"); }) as typeof fetch);
    await expect(gateway.findByCloid(masterAddress, cloid)).resolves.toEqual({ state: "unknown" });
  });
});

describe("multi-account no-submit live preflight", () => {
  it("verifies the encrypted signer and executable plan without a CLOID lookup, nonce, or write", async () => {
    const originalKek = process.env.TRENDATLAS_AGENT_KEK_B64;
    process.env.TRENDATLAS_AGENT_KEK_B64 = Buffer.alloc(32, 9).toString("base64");
    const encryptedSecret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).encrypt(privateKey);
    const candidate: EligibleAccount & { encryptedSecret: typeof encryptedSecret } = {
      userId: "user-a",
      accountId: "account-a",
      masterAddress,
      agentAddress,
      agentName: "TA-1234abcd",
      authorizationId: "auth-a",
      connectionStatus: "read_only_connected",
      authorizationStatus: "authorized",
      ownershipVerifiedAt: "2026-09-01T00:00:00Z",
      agentAuthorizedAt: "2026-09-01T00:00:00Z",
      autoTradingRequested: true,
      executionStatus: "ready",
      hasEncryptedSecret: true,
      encryptedSecret
    };
    const target: AuthorizedTarget = { strategyVersion: "v1", closedDay: "2026-09-03", signalId: "signal", asset: "ETH", exposure: 1, stale: false, executionGate: "approved" };
    const markets = new Map<"BTC" | "ETH", MarketSpec>([
      ["BTC", { asset: "BTC", markPrice: 60_000, minNotionalUsd: 10, sizeDecimals: 5 }],
      ["ETH", { asset: "ETH", markPrice: 2_500, minNotionalUsd: 10, sizeDecimals: 4 }]
    ]);
    const findByCloid = vi.fn();
    const writeIoc = vi.fn();
    const account: AccountState = { equityUsd: 100, positions: [], openOrderCount: 0 };
    const gateway: ExchangeGateway = {
      readAccount: async () => account,
      readMarkets: async () => markets,
      userRole: async () => ({ role: "agent", user: masterAddress }),
      agentAuthorization: async () => ({ authorized: true, validUntilMs: Date.parse("2100-01-01T00:00:00Z") }),
      findByCloid,
      writeIoc
    };

    try {
      await expect(preflightMultiAccountCandidates([candidate], target, gateway)).resolves.toEqual([
        { accountId: "account-a", status: "READY", actionCount: 1 }
      ]);
      expect(findByCloid).not.toHaveBeenCalled();
      expect(writeIoc).not.toHaveBeenCalled();
    } finally {
      if (originalKek === undefined) delete process.env.TRENDATLAS_AGENT_KEK_B64;
      else process.env.TRENDATLAS_AGENT_KEK_B64 = originalKek;
    }
  });

  it("keeps the command dry-run-gated and exposes no live runner", () => {
    const root = process.cwd();
    const runner = fs.readFileSync(path.join(root, "scripts/run-multi-account-live-preflight.ts"), "utf8");
    const packageJson = fs.readFileSync(path.join(root, "package.json"), "utf8");
    expect(runner.indexOf('mode !== "dry_run"')).toBeLessThan(runner.indexOf('import("@/server/multi-account-executor/hyperliquid-live-gateway")'));
    expect(runner).not.toMatch(/writeIoc|reserveNonce|runEligibleAccountsOnce/);
    expect(packageJson).toContain('"multi-account:live-preflight"');
    expect(packageJson).not.toContain('"multi-account:live"');
  });
});

describe("ambiguous live submission recovery", () => {
  it("stops without retry when both the write and post-write CLOID lookup fail", async () => {
    const originalKek = process.env.TRENDATLAS_AGENT_KEK_B64;
    process.env.TRENDATLAS_AGENT_KEK_B64 = Buffer.alloc(32, 10).toString("base64");
    const encryptedSecret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).encrypt(privateKey);
    const candidate = {
      userId: "user-a", accountId: "account-a", masterAddress, agentAddress, agentName: "TA-1234abcd",
      authorizationId: "auth-a", connectionStatus: "read_only_connected", authorizationStatus: "authorized",
      ownershipVerifiedAt: "2026-09-01T00:00:00Z", agentAuthorizedAt: "2026-09-01T00:00:00Z",
      autoTradingRequested: true, executionStatus: "ready" as const, hasEncryptedSecret: true, encryptedSecret
    };
    const records: string[] = [];
    const repository: ExecutionRepository = {
      listMultiAccountCandidates: async () => [candidate],
      tryAcquire: async () => true,
      release: async () => undefined,
      reserveNonce: async () => nonce,
      createRun: async () => "run",
      recordAction: async (_run, _action, _cloid, state) => { records.push(state); },
      finishRun: async () => undefined,
      setAccountStatus: async () => undefined
    };
    const findByCloid = vi.fn()
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new Error("lookup unavailable"));
    const writeIoc = vi.fn(async () => { throw new Error("transport timeout"); });
    const gateway: ExchangeGateway = {
      readAccount: async () => ({ equityUsd: 100, positions: [], openOrderCount: 0 }),
      readMarkets: async () => new Map([
        ["BTC", { asset: "BTC", markPrice: 60_000, minNotionalUsd: 10, sizeDecimals: 5 }],
        ["ETH", { asset: "ETH", markPrice: 2_500, minNotionalUsd: 10, sizeDecimals: 4 }]
      ]),
      userRole: async () => ({ role: "agent", user: masterAddress }),
      agentAuthorization: async () => ({ authorized: true, validUntilMs: Date.parse("2100-01-01T00:00:00Z") }),
      findByCloid,
      writeIoc
    };
    const target: AuthorizedTarget = { strategyVersion: "v1", closedDay: "2026-09-03", signalId: "signal", asset: "ETH", exposure: 1, stale: false, executionGate: "approved" };

    try {
      await expect(new MultiAccountExecutor(repository, gateway, "live").runAllForTarget(target)).resolves.toEqual([
        { accountId: "account-a", status: "UNKNOWN_SUBMISSION_STATE" }
      ]);
      expect(writeIoc).toHaveBeenCalledTimes(1);
      expect(findByCloid).toHaveBeenCalledTimes(2);
      expect(records).toEqual(["NOT_SUBMITTED", "AMBIGUOUS"]);
    } finally {
      if (originalKek === undefined) delete process.env.TRENDATLAS_AGENT_KEK_B64;
      else process.env.TRENDATLAS_AGENT_KEK_B64 = originalKek;
    }
  });
});
