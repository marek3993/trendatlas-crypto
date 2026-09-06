import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { createEnvironmentAgentSecretProtector } from "@/lib/hyperliquid/agent-authorization";
import { privateKeyToAccount } from "viem/accounts";
import { AuthorityError, loadCanonicalRunTarget, parseAuthorizedTarget } from "@/server/multi-account-executor/authority";
import { deterministicCloid } from "@/server/multi-account-executor/cloid";
import { MultiAccountExecutor, isEligibleMultiAccount, type ExchangeGateway, type ExecutionRepository } from "@/server/multi-account-executor/engine";
import { HyperliquidDryRunGateway } from "@/server/multi-account-executor/dry-run-gateway";
import { canWriteExchange, executionMode } from "@/server/multi-account-executor/mode";
import { buildPlan } from "@/server/multi-account-executor/planner";
import type { AccountState, AuthorizedTarget, EligibleAccount, MarketSpec } from "@/server/multi-account-executor/types";

const webRoot = process.cwd();
const repoRoot = path.resolve(webRoot, "..");
const source = (relative: string) => fs.readFileSync(path.join(webRoot, relative), "utf8");
const migration = source("supabase/migrations/202609050001_create_multi_account_execution.sql");
const engineSource = source("src/server/multi-account-executor/engine.ts");
const repositorySource = source("src/server/multi-account-executor/repository.ts");
const workerSource = source("src/server/multi-account-executor/worker.ts");
const dryRunGatewaySource = source("src/server/multi-account-executor/dry-run-gateway.ts");
const dryRunRunnerSource = source("scripts/run-multi-account-dry-run.ts");
const productionSource = fs.readFileSync(path.join(repoRoot, "scripts/execution/run_trendatlas_production.py"), "utf8");

const target = (asset: "BTC" | "ETH" | "CASH", exposure = asset === "CASH" ? 0 : 1): AuthorizedTarget => ({ strategyVersion: "v1", closedDay: "2026-09-03", signalId: `signal-${asset}`, asset, exposure, stale: false, executionGate: asset === "CASH" ? "no_action" : "approved" });
const markets = new Map<"BTC" | "ETH", MarketSpec>([
  ["BTC", { asset: "BTC", markPrice: 100, minNotionalUsd: 10, sizeDecimals: 3 }],
  ["ETH", { asset: "ETH", markPrice: 10, minNotionalUsd: 10, sizeDecimals: 3 }]
]);
const account = (equityUsd = 100, positions: AccountState["positions"] = [], openOrderCount = 0): AccountState => ({ equityUsd, positions, openOrderCount });
const candidate = (overrides: Partial<EligibleAccount> = {}): EligibleAccount => ({ userId: "user-a", accountId: "account-a", masterAddress: "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", agentAddress: "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", agentName: "TA-1234abcd", authorizationId: "auth-a", connectionStatus: "read_only_connected", authorizationStatus: "authorized", ownershipVerifiedAt: "2026-09-01T00:00:00Z", agentAuthorizedAt: "2026-09-01T00:00:00Z", autoTradingRequested: true, executionStatus: "ready", hasEncryptedSecret: true, ...overrides });
const validAgentAuthorization = async () => ({ authorized: true, validUntilMs: Date.parse("2100-01-01T00:00:00Z") });

function authorityFixture(asset: "BTC" | "ETH" | "CASH", exposure = asset === "CASH" ? 0 : 1) {
  const signal = "canonical-signal";
  const snapshot = { artifact_type: "authority_latest_successful_snapshot", schema_version: 1, latest_authoritative_attempt_status: "success", attempt_stage_status: "success", run_id: "run-1", target_closed_day_utc: "2026-09-03", strategy_artifact_closed_day_utc: "2026-09-03", currentness_status: "current", app_runtime_snapshot: { execution_intent_summary: { signal_id: signal, target_asset: asset, target_exposure: exposure, stale_signal: false }, gate_summary: { status: asset === "CASH" ? "no_action" : "ready", approval_gate_status: "approved_and_applied", would_place_real_order: asset !== "CASH", production_signal_context: { strategy_version: "v1", closed_day: "2026-09-03", signal_id: signal, target_asset: asset, target_exposure: exposure, validation_status: "passed", candidate_asset: asset === "CASH" ? "ETH" : "BTC" } } } };
  const attempt = { artifact_type: "authority_latest_attempt_status", schema_version: 1, latest_authoritative_attempt_status: "success", attempt_stage_status: "success", run_id: "run-1", target_closed_day_utc: "2026-09-03" };
  return { snapshot, attempt };
}

describe("multi-account executor authority and eligibility", () => {
  it("uses the authorized target rather than the model candidate", () => {
    const { snapshot, attempt } = authorityFixture("CASH");
    expect(parseAuthorizedTarget(snapshot, attempt).asset).toBe("CASH");
  });
  it("honors CASH even when the model candidate is ETH", () => {
    const { snapshot, attempt } = authorityFixture("CASH");
    expect(parseAuthorizedTarget(snapshot, attempt)).toMatchObject({ asset: "CASH", exposure: 0 });
  });
  it("blocks stale authority", () => {
    const { snapshot, attempt } = authorityFixture("BTC");
    snapshot.currentness_status = "stale";
    expect(() => parseAuthorizedTarget(snapshot, attempt)).toThrow(AuthorityError);
  });
  it("blocks missing or invalid authority", () => expect(() => parseAuthorizedTarget({}, {})).toThrow(AuthorityError));
  it("blocks unsupported targets", () => {
    const { snapshot, attempt } = authorityFixture("BTC");
    snapshot.app_runtime_snapshot.execution_intent_summary.target_asset = "DOGE";
    snapshot.app_runtime_snapshot.gate_summary.production_signal_context.target_asset = "DOGE";
    expect(() => parseAuthorizedTarget(snapshot, attempt)).toThrow(AuthorityError);
  });
  it("skips an unauthorized agent", () => expect(isEligibleMultiAccount(candidate({ authorizationStatus: "pending" }))).toBe(false));
  it("skips auto trading OFF", () => expect(isEligibleMultiAccount(candidate({ autoTradingRequested: false }))).toBe(false));
  it("requires a stored encrypted secret", () => expect(isEligibleMultiAccount(candidate({ hasEncryptedSecret: false }))).toBe(false));
  it("allows an interrupted executing account to reach lease and CLOID recovery", () => expect(isEligibleMultiAccount(candidate({ executionStatus: "executing" }))).toBe(true));
  it("requires the explicit multi-user authorization join, not an account address alone", () => {
    expect(repositorySource).toContain('from("hyperliquid_agent_authorizations")');
    expect(repositorySource).toContain("hyperliquid_accounts!inner");
    expect(repositorySource).toContain('.eq("auto_trading_requested", true)');
    expect(repositorySource).toContain('.in("execution_status", ["ready", "aligned", "executing"])');
  });
  it("rechecks the exact agent-to-master binding", () => expect(engineSource).toContain('role.user?.toLowerCase() !== account.masterAddress.toLowerCase()'));
  it("rechecks the exact named agent grant and expiry", () => {
    expect(engineSource).toContain("account.agentName");
    expect(engineSource).toContain("authorization.validUntilMs <= Date.now()");
  });
  it("loads only a fingerprint-bound target from the currently locked canonical run", async () => {
    const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "trendatlas-canonical-target-"));
    const productionValue = {
      artifact_type: "current_strategy_snapshot", schema_version: 4, closed_day: "2026-09-03", strategy_version: "v1",
      validation: { status: "passed" }, execution_intent: { signal_id: "signal-ETH", target_asset: "ETH", target_exposure: 1, stale_signal: false }
    };
    const productionText = `${JSON.stringify(productionValue)}\n`;
    const productionHash = createHash("sha256").update(productionText).digest("hex");
    const intentValue = { as_of_source: "2026-09-03", strategy_model: "v1", signal_id: "signal-ETH", target_asset: "ETH", target_size_pct: 1, stale_signal: false, source_fingerprints: { production_snapshot_sha256: productionHash } };
    const intentText = `${JSON.stringify(intentValue)}\n`;
    const accountText = `${JSON.stringify({ account_address: candidate().masterAddress })}\n`;
    const gateValue = {
      status: "ready_if_enabled", approval_gate_status: "approved_and_applied", real_orders_enabled: true, would_place_real_order: true,
      production_signal_context: { strategy_version: "v1", closed_day: "2026-09-03", signal_id: "signal-ETH", target_asset: "ETH", target_exposure: 1, validation_status: "passed" },
      source_fingerprints: {
        production_snapshot_sha256: productionHash,
        intent_sha256: createHash("sha256").update(intentText).digest("hex"),
        account_snapshot_sha256: createHash("sha256").update(accountText).digest("hex")
      }
    };
    const write = (relative: string, value: string) => {
      const destination = path.join(temporaryRoot, relative);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.writeFileSync(destination, value);
    };
    write("outputs/production/current_strategy_snapshot.json", productionText);
    write("outputs/execution/intents/latest_execution_intent.json", intentText);
    write("outputs/execution/live_gate/latest_real_order_gate_decision.json", `${JSON.stringify(gateValue)}\n`);
    write("outputs/execution/read_only/hyperliquid_account_snapshot.json", accountText);
    const originalRun = process.env.MRV1_CURRENT_AUTHORITY_RUN_ID;
    const originalDay = process.env.MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY;
    process.env.MRV1_CURRENT_AUTHORITY_RUN_ID = "run-1";
    process.env.MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY = "2026-09-03";
    try {
      await expect(loadCanonicalRunTarget(temporaryRoot, "run-1", "signal-ETH")).resolves.toMatchObject({ asset: "ETH", exposure: 1, closedDay: "2026-09-03" });
      write("outputs/execution/read_only/hyperliquid_account_snapshot.json", `${JSON.stringify({ changed: true })}\n`);
      await expect(loadCanonicalRunTarget(temporaryRoot, "run-1", "signal-ETH")).rejects.toThrow("canonical source fingerprints do not match");
    } finally {
      if (originalRun === undefined) delete process.env.MRV1_CURRENT_AUTHORITY_RUN_ID; else process.env.MRV1_CURRENT_AUTHORITY_RUN_ID = originalRun;
      if (originalDay === undefined) delete process.env.MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY; else process.env.MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY = originalDay;
      fs.rmSync(temporaryRoot, { recursive: true, force: true });
    }
  });
});

describe("multi-account executor planning", () => {
  it("sizes from each account's current real equity", () => expect(buildPlan(target("ETH"), account(1000), markets).actions[0].requestedNotionalUsd).toBe(1000));
  it("naturally changes future size after a deposit without using PnL", () => {
    expect(buildPlan(target("ETH"), account(500), markets).actions[0].requestedNotionalUsd).toBe(500);
    expect(buildPlan(target("ETH"), account(1000), markets).actions[0].requestedNotionalUsd).toBe(1000);
  });
  it("does not fall back to Marek equity", () => expect(engineSource).not.toContain("Marek"));
  it("blocks a target below the executable minimum", () => expect(buildPlan(target("ETH"), account(5), markets).state).toBe("BLOCKED"));
  it("plans CASH to asset as ENTER", () => expect(buildPlan(target("ETH"), account(), markets).state).toBe("ENTER"));
  it("plans asset to CASH as reduce-only EXIT", () => expect(buildPlan(target("CASH"), account(100, [{ asset: "BTC", size: 1, markPrice: 100 }]), markets).actions[0]).toMatchObject({ action: "EXIT", reduceOnly: true }));
  it("plans BTC to ETH with exit before entry", () => expect(buildPlan(target("ETH"), account(100, [{ asset: "BTC", size: 1, markPrice: 100 }]), markets).actions.map((action) => action.action)).toEqual(["EXIT", "ENTER"]));
  it("plans a same-asset increase", () => expect(buildPlan(target("ETH", 1), account(100, [{ asset: "ETH", size: 5, markPrice: 10 }]), markets).actions[0]).toMatchObject({ action: "RESIZE", reduceOnly: false }));
  it("plans a same-asset reduction as reduce-only", () => expect(buildPlan(target("ETH", 0.5), account(100, [{ asset: "ETH", size: 10, markPrice: 10 }]), markets).actions[0]).toMatchObject({ action: "RESIZE", reduceOnly: true }));
  it("leaves an aligned account alone", () => expect(buildPlan(target("ETH"), account(100, [{ asset: "ETH", size: 10, markPrice: 10 }]), markets).state).toBe("NO_ACTION"));
  it("treats a same-asset dust residual below the exchange minimum as precision-limited alignment", () => {
    expect(buildPlan(target("ETH"), account(100, [{ asset: "ETH", size: 9.5, markPrice: 10 }]), markets)).toMatchObject({
      state: "NO_ACTION",
      actions: [],
      reason: "precision-limited residual below exchange minimum"
    });
  });
  it("blocks unsupported third-party positions without closing them", () => expect(buildPlan(target("ETH"), account(100, [{ asset: "SOL", size: 1, markPrice: 100 }]), markets).state).toBe("BLOCKED"));
  it("blocks unexpected open orders", () => expect(buildPlan(target("ETH"), account(100, [], 1), markets).state).toBe("BLOCKED"));
});

describe("idempotency, modes, and isolation", () => {
  const cloidInput = { userId: "u", accountId: "a", signalId: "s", closedDay: "2026-09-03", target: "ETH", action: "ENTER", leg: 0, attempt: 0 };
  it("creates the same CLOID for the same reconciliation", () => expect(deterministicCloid(cloidInput)).toBe(deterministicCloid(cloidInput)));
  it("creates distinct per-user CLOID namespaces", () => expect(deterministicCloid(cloidInput)).not.toBe(deterministicCloid({ ...cloidInput, userId: "other" })));
  it("uses a 128-bit Hyperliquid CLOID format", () => expect(deterministicCloid(cloidInput)).toMatch(/^0x[0-9a-f]{32}$/));
  it("queries a CLOID before it can write", () => expect(engineSource.indexOf("findByCloid")).toBeLessThan(engineSource.indexOf("writeIoc")));
  it("durably journals each live action before CLOID recovery or submission", () => {
    const liveBranch = engineSource.indexOf("if (!canWriteExchange");
    const prepared = engineSource.indexOf('recordAction(runId, action, cloid, "NOT_SUBMITTED")', liveBranch);
    const recovery = engineSource.indexOf("findByCloid(account.masterAddress, cloid)", liveBranch);
    const submit = engineSource.indexOf("writeIoc({", liveBranch);
    expect(prepared).toBeGreaterThan(liveBranch);
    expect(prepared).toBeLessThan(recovery);
    expect(recovery).toBeLessThan(submit);
  });
  it("persists NOT_SUBMITTED before recovering a previously filled live CLOID", async () => {
    const originalKek = process.env.TRENDATLAS_AGENT_KEK_B64;
    process.env.TRENDATLAS_AGENT_KEK_B64 = Buffer.alloc(32, 7).toString("base64");
    const privateKey = `0x${"11".repeat(32)}` as const;
    const agentAddress = privateKeyToAccount(privateKey).address.toLowerCase();
    const encryptedSecret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64)
      .encrypt(privateKey);
    const events: string[] = [];
    let accountRead = 0;
    const repository: ExecutionRepository = {
      listMultiAccountCandidates: async () => [{ ...candidate({ agentAddress }), encryptedSecret }],
      tryAcquire: async () => true,
      release: async () => undefined,
      reserveNonce: async () => 1n,
      createRun: async () => "run",
      recordAction: async (_runId, _action, _cloid, state) => { events.push(`journal:${state}`); },
      finishRun: async () => undefined,
      setAccountStatus: async () => undefined
    };
    const exchange: ExchangeGateway = {
      readAccount: async () => accountRead++ === 0 ? account() : account(100, [{ asset: "ETH", size: 10, markPrice: 10 }]),
      readMarkets: async () => markets,
      userRole: async () => ({ role: "agent", user: candidate().masterAddress }),
      agentAuthorization: validAgentAuthorization,
      findByCloid: async () => { events.push("find"); return { state: "filled", orderId: "known-order" }; },
      writeIoc: async () => { events.push("write"); return {}; }
    };

    try {
      const results = await new MultiAccountExecutor(repository, exchange, "live").runAllForTarget(target("ETH"));
      expect(results).toEqual([{ accountId: "account-a", status: "FILLED_AND_ALIGNED" }]);
      expect(events).toEqual(["journal:NOT_SUBMITTED", "find", "journal:KNOWN"]);
    } finally {
      if (originalKek === undefined) delete process.env.TRENDATLAS_AGENT_KEK_B64;
      else process.env.TRENDATLAS_AGENT_KEK_B64 = originalKek;
    }
  });
  it("recovers a previously known order without another write", () => expect(engineSource).toContain('if (!known)'));
  it("records unknown submissions without blind retry", () => expect(engineSource).toContain('"UNKNOWN_SUBMISSION_STATE"'));
  it("reserves monotonic per-agent nonces in the database", () => {
    expect(migration).toContain("multi_account_agent_nonces");
    expect(migration).toContain("last_nonce + 1");
  });
  it("uses a per-account distributed lease lock", () => {
    expect(migration).toContain("multi_account_execution_locks");
    expect(engineSource).toContain("tryAcquire(account.accountId");
  });
  it("defaults global execution mode to disabled", () => expect(executionMode(undefined)).toBe("disabled"));
  it("does not grant write capability in disabled or dry-run mode", () => {
    expect(canWriteExchange("disabled")).toBe(false);
    expect(canWriteExchange("dry_run")).toBe(false);
    expect(canWriteExchange("live")).toBe(true);
  });
  it("requires an explicit live environment value", () => expect(executionMode("anything-else")).toBe("disabled"));
  it("keeps the dry-run gateway unable to submit or inspect executable orders", async () => {
    const gateway = new HyperliquidDryRunGateway();
    await expect(gateway.findByCloid(candidate().masterAddress, "0x00000000000000000000000000000000")).rejects.toThrow("Dry-run gateway cannot inspect executable orders.");
    await expect(gateway.writeIoc({} as never)).rejects.toThrow("Dry-run gateway cannot submit orders.");
    expect(dryRunGatewaySource).toContain("https://api.hyperliquid.xyz/info");
    expect(dryRunGatewaySource).not.toContain("https://api.hyperliquid.xyz/exchange");
  });

  it("refuses every runner mode except exact dry_run before importing the worker", () => {
    const guard = dryRunRunnerSource.indexOf('mode !== "dry_run"');
    const workerImport = dryRunRunnerSource.indexOf('import("@/server/multi-account-executor/worker")');
    expect(guard).toBeGreaterThanOrEqual(0);
    expect(workerImport).toBeGreaterThan(guard);
    expect(dryRunRunnerSource).toContain('results.length === 0 || results.some(({ status }) => status !== "DRY_RUN")');
  });

  it("keeps the worker outside browser routes and server actions", () => {
    expect(workerSource).toContain('import "server-only"');
    expect(workerSource).not.toContain('"use server"');
    expect(workerSource).not.toMatch(/app\/api|route\.ts/);
  });
});

describe("durable journal and production boundary", () => {
  it("gives users read-only access to only their own run history", () => {
    expect(migration).toContain("multi_account_execution_runs_select_own");
    expect(migration).toContain("multi_account_execution_actions_select_own");
    expect(migration).not.toMatch(/grant\s+(insert|update|delete)[^;]*multi_account_execution_(runs|actions)[^;]*authenticated/i);
  });
  it("keeps encrypted secrets unavailable to browser roles", () => expect(migration).not.toContain("hyperliquid_agent_secrets from public, anon, authenticated;\ngrant"));
  it("records only the narrow IOC write capability", () => {
    expect(engineSource).toContain("writeIoc");
    expect(engineSource).not.toMatch(/usdSend|spotSend|withdraw|transfer|approveAgent|leverage/i);
  });
  it("requires read-back alignment rather than transport success", () => {
    expect(engineSource).toContain("const finalPlan = buildPlan(target, after, markets)");
    expect(engineSource).toContain("after.openOrderCount !== 0");
  });
  it("treats residuals outside tolerance as unaligned", () => expect(engineSource).toContain('if (!isAligned(finalPlan) || after.openOrderCount !== 0)'));
  it("correctly treats zero managed positions as CASH", () => expect(buildPlan(target("CASH"), account(), markets).state).toBe("NO_ACTION"));
  it("delegates only the execution stage and skips the legacy signer in multi-account mode", () => {
    expect(productionSource).toContain('self.execution_backend == "multi_account"');
    expect(productionSource).toContain("run_multi_account_backend");
    expect(productionSource.indexOf('if self.execution_backend == "multi_account"')).toBeLessThan(productionSource.indexOf("signer_validation = self.signer_validator()"));
  });
  it("does not send a write in disabled mode", async () => {
    const writeIoc = vi.fn();
    const repository: ExecutionRepository = { listMultiAccountCandidates: async () => [candidate()], tryAcquire: async () => true, release: async () => undefined, reserveNonce: async () => 1n, createRun: async () => "run", recordAction: async () => undefined, finishRun: async () => undefined, setAccountStatus: async () => undefined };
    const exchange: ExchangeGateway = { readAccount: async () => account(), readMarkets: async () => markets, userRole: async () => ({ role: "agent", user: candidate().masterAddress }), agentAuthorization: validAgentAuthorization, findByCloid: async () => null, writeIoc };
    await new MultiAccountExecutor(repository, exchange, "disabled").runAllForTarget(target("ETH"));
    expect(writeIoc).not.toHaveBeenCalled();
  });
  it("does not send a write in dry-run mode", async () => {
    const writeIoc = vi.fn();
    const repository: ExecutionRepository = { listMultiAccountCandidates: async () => [candidate()], tryAcquire: async () => true, release: async () => undefined, reserveNonce: async () => 1n, createRun: async () => "run", recordAction: async () => undefined, finishRun: async () => undefined, setAccountStatus: async () => undefined };
    const exchange: ExchangeGateway = { readAccount: async () => account(), readMarkets: async () => markets, userRole: async () => ({ role: "agent", user: candidate().masterAddress }), agentAuthorization: validAgentAuthorization, findByCloid: async () => null, writeIoc };
    await new MultiAccountExecutor(repository, exchange, "dry_run").runAllForTarget(target("ETH"));
    expect(writeIoc).not.toHaveBeenCalled();
  });
  it("blocks an expired named-agent grant before reading account state", async () => {
    const readAccount = vi.fn(async () => account());
    const repository: ExecutionRepository = { listMultiAccountCandidates: async () => [candidate()], tryAcquire: async () => true, release: async () => undefined, reserveNonce: async () => 1n, createRun: async () => "run", recordAction: async () => undefined, finishRun: async () => undefined, setAccountStatus: async () => undefined };
    const exchange: ExchangeGateway = { readAccount, readMarkets: async () => markets, userRole: async () => ({ role: "agent", user: candidate().masterAddress }), agentAuthorization: async () => ({ authorized: true, validUntilMs: 0 }), findByCloid: async () => null, writeIoc: async () => ({}) };

    const results = await new MultiAccountExecutor(repository, exchange, "dry_run").runAllForTarget(target("ETH"));

    expect(results).toEqual([{ accountId: "account-a", status: "BLOCKED", reason: "agent authorization is missing or expired" }]);
    expect(readAccount).not.toHaveBeenCalled();
  });
  it("journals dry-run actions without reserving a nonce or writing", async () => {
    const recordAction = vi.fn();
    const reserveNonce = vi.fn(async () => 1n);
    const writeIoc = vi.fn();
    const repository: ExecutionRepository = {
      listMultiAccountCandidates: async () => [candidate()],
      tryAcquire: async () => true,
      release: async () => undefined,
      reserveNonce,
      createRun: async () => "run",
      recordAction,
      finishRun: async () => undefined,
      setAccountStatus: async () => undefined
    };
    const exchange: ExchangeGateway = {
      readAccount: async () => account(),
      readMarkets: async () => markets,
      userRole: async () => ({ role: "agent", user: candidate().masterAddress }),
      agentAuthorization: validAgentAuthorization,
      findByCloid: async () => null,
      writeIoc
    };

    const results = await new MultiAccountExecutor(repository, exchange, "dry_run").runAllForTarget(target("ETH"));

    expect(results).toEqual([{ accountId: "account-a", status: "DRY_RUN" }]);
    expect(recordAction).toHaveBeenCalledWith(
      "run",
      expect.objectContaining({ action: "ENTER", asset: "ETH" }),
      expect.stringMatching(/^0x[0-9a-f]{32}$/),
      "NOT_SUBMITTED"
    );
    expect(reserveNonce).not.toHaveBeenCalled();
    expect(writeIoc).not.toHaveBeenCalled();
  });

  it("isolates one account failure from other accounts", async () => {
    const writeIoc = vi.fn();
    const first = candidate({ accountId: "a", masterAddress: "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", agentAddress: "0x1111111111111111111111111111111111111111" });
    const broken = candidate({ accountId: "b", masterAddress: "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", agentAddress: "0x2222222222222222222222222222222222222222" });
    const third = candidate({ accountId: "c", masterAddress: "0xdddddddddddddddddddddddddddddddddddddddd", agentAddress: "0x3333333333333333333333333333333333333333" });
    const released: string[] = [];
    const repository: ExecutionRepository = { listMultiAccountCandidates: async () => [first, broken, third], tryAcquire: async () => true, release: async (accountId) => { released.push(accountId); }, reserveNonce: async () => 1n, createRun: async () => "run", recordAction: async () => undefined, finishRun: async () => undefined, setAccountStatus: async () => undefined };
    const exchange: ExchangeGateway = { readAccount: async () => account(), readMarkets: async () => markets, userRole: async (agent) => {
      if (agent === broken.agentAddress) throw new Error("account B adapter failure");
      return { role: "agent", user: agent === first.agentAddress ? first.masterAddress : third.masterAddress };
    }, agentAuthorization: validAgentAuthorization, findByCloid: async () => null, writeIoc };
    const results = await new MultiAccountExecutor(repository, exchange, "dry_run").runAllForTarget(target("ETH"));
    expect(results).toEqual([
      { accountId: "a", status: "DRY_RUN" },
      { accountId: "b", status: "FAILED", reason: "Account execution could not be verified." },
      { accountId: "c", status: "DRY_RUN" }
    ]);
    expect(released.sort()).toEqual(["a", "b", "c"]);
    expect(writeIoc).not.toHaveBeenCalled();
  });
  it("stops the sequential production batch after the first unsafe account result", async () => {
    const first = candidate({ accountId: "a" });
    const second = candidate({ accountId: "b", masterAddress: "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" });
    const userRole = vi.fn(async () => ({ role: "agent", user: "0xcccccccccccccccccccccccccccccccccccccccc" }));
    const repository: ExecutionRepository = {
      listMultiAccountCandidates: async () => [first, second], tryAcquire: async () => true, release: async () => undefined,
      reserveNonce: async () => 1n, createRun: async () => "run", recordAction: async () => undefined,
      finishRun: async () => undefined, setAccountStatus: async () => undefined
    };
    const exchange: ExchangeGateway = {
      readAccount: async () => account(), readMarkets: async () => markets, userRole,
      agentAuthorization: validAgentAuthorization, findByCloid: async () => null, writeIoc: async () => ({})
    };

    const results = await new MultiAccountExecutor(repository, exchange, "live", 1, { stopOnUnsafeResult: true }).runAllForTarget(target("ETH"));

    expect(results).toEqual([
      { accountId: "a", status: "BLOCKED", reason: "agent binding is invalid" },
      { accountId: "b", status: "BLOCKED", reason: "batch stopped after another account failed" }
    ]);
    expect(userRole).toHaveBeenCalledTimes(1);
  });
  it("does not log plaintext agent secrets", () => expect(engineSource).not.toMatch(/console\.(log|error).*agentPrivateKey|agentPrivateKey.*console\.(log|error)/));
  it("requires more than a user preference before trading", () => {
    expect(isEligibleMultiAccount(candidate({ hasEncryptedSecret: false }))).toBe(false);
    expect(executionMode(undefined)).toBe("disabled");
  });
});
