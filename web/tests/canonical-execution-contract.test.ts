import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadCanonicalRunTarget } from "@/server/multi-account-executor/authority";
import { runPreflightedBatch, isolateDuplicateWallets, summarizeAccountBatch, sharedFailureReport } from "@/server/multi-account-executor/batch";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true }); vi.unstubAllEnvs(); });
function fixture(asset = "AVAX", exposure = 1.25, authorized = true) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "trendatlas-target-")); roots.push(root);
  const write = (file: string, value: unknown) => {
    const dest = path.join(root, file); fs.mkdirSync(path.dirname(dest), { recursive: true });
    const text = `${JSON.stringify(value)}\n`; fs.writeFileSync(dest, text); return createHash("sha256").update(text).digest("hex");
  };
  const day = "2026-09-24", signalId = `signal-${asset}`;
  const production = { artifact_type: "current_strategy_snapshot", schema_version: 4, closed_day: day, strategy_version: "validated-model", strategy_status: "ready", validation: { status: "passed" }, trend_permission_active: authorized && asset !== "CASH", execution_intent: { signal_id: signalId, target_asset: asset, target_exposure: exposure, stale_signal: false, allow_live_order_candidate: authorized && asset !== "CASH" } };
  const productionHash = write("outputs/production/current_strategy_snapshot.json", production);
  const intentHash = write("outputs/execution/intents/latest_execution_intent.json", { as_of_source: day, strategy_model: "validated-model", signal_id: signalId, target_asset: asset, target_size_pct: exposure, stale_signal: false, source_fingerprints: { production_snapshot_sha256: productionHash } });
  const accountHash = write("outputs/execution/read_only/hyperliquid_account_snapshot.json", { as_of_utc: "2026-09-25T06:00:00Z" });
  const gate = { status: "blocked", would_place_real_order: false, approval_gate_status: "old-unrelated-approval", production_signal_context: { strategy_version: "validated-model", closed_day: day, signal_id: signalId, target_asset: asset, target_exposure: exposure, validation_status: "passed" }, source_fingerprints: { production_snapshot_sha256: productionHash, intent_sha256: intentHash, account_snapshot_sha256: accountHash } };
  write("outputs/execution/live_gate/latest_real_order_gate_decision.json", gate);
  write("execution/config/execution_mode.json", { kill_switch: false });
  vi.stubEnv("MRV1_CURRENT_AUTHORITY_RUN_ID", "run-current"); vi.stubEnv("MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY", day);
  return { root, write, production, gate, signalId, load: () => loadCanonicalRunTarget(root, "run-current", signalId) };
}

describe("current strategy execution authority", () => {
  it.each(["AVAX", "NEWCOIN123", "CASH"])("accepts validated %s without a prior publish or approval", async (asset) => {
    const f = fixture(asset, asset === "CASH" ? 0 : 1.25); await expect(f.load()).resolves.toMatchObject({ asset, exposure: asset === "CASH" ? 0 : 1.25 });
  });
  it("does not turn account-specific blocked state into a common target veto", async () => { await expect(fixture().load()).resolves.toMatchObject({ asset: "AVAX" }); });
  it("still rejects fingerprint drift", async () => { const f = fixture(); f.write("outputs/execution/read_only/hyperliquid_account_snapshot.json", { changed: true }); await expect(f.load()).rejects.toThrow("fingerprint"); });
  it("delegates missing owner context to fresh per-account validation only for the explicit multi-account scope", async () => {
    const f = fixture(); fs.unlinkSync(path.join(f.root, "outputs/execution/read_only/hyperliquid_account_snapshot.json"));
    f.write("outputs/execution/live_gate/latest_real_order_gate_decision.json", { ...f.gate, account_validation_scope: "per_account_exchange", account_snapshot_available: false, source_fingerprints: { ...f.gate.source_fingerprints, account_snapshot_sha256: null } });
    await expect(f.load()).rejects.toThrow("account context");
    vi.stubEnv("MRV1_EXECUTION_BACKEND", "multi_account");
    await expect(f.load()).resolves.toMatchObject({ asset: "AVAX" });
  });
  it("still enforces exact current run binding", async () => { const f = fixture(); vi.stubEnv("MRV1_CURRENT_AUTHORITY_RUN_ID", "different"); await expect(f.load()).rejects.toThrow("run id"); });
  it("isolates changed owner context in explicit multi-account scope", async () => {
    const f = fixture(); f.write("outputs/execution/read_only/hyperliquid_account_snapshot.json", { changed: true });
    f.write("outputs/execution/live_gate/latest_real_order_gate_decision.json", { ...f.gate, account_validation_scope: "per_account_exchange" });
    vi.stubEnv("MRV1_EXECUTION_BACKEND", "multi_account");
    await expect(f.load()).resolves.toMatchObject({ asset: "AVAX" });
  });
  it("blocks entry without strategy permission", async () => { await expect(fixture("AVAX", 1.25, false).load()).rejects.toThrow("not authorized"); });
  it("retains the single emergency switch", async () => { const f = fixture(); f.write("execution/config/execution_mode.json", { kill_switch: true }); await expect(f.load()).rejects.toThrow("emergency"); });
  it.each([["../AVAX", 1.25], ["CASH", 1], ["AVAX", -1]])("rejects invalid target %s/%s", async (asset, exposure) => { await expect(fixture(String(asset), Number(exposure)).load()).rejects.toThrow(); });
});

describe("independent account batch", () => {
  it("classifies shared network failures and possible writes explicitly", () => {
    expect(sharedFailureReport("metadata", "run", false, "signal-bound")).toMatchObject({ runId: "run", signalId: "signal-bound", failureKind: "retryable" });
    expect(sharedFailureReport("metadata", "run", false)).toMatchObject({ failureKind: "retryable", realOrderSent: false });
    expect(sharedFailureReport("authority", "run", false)).toMatchObject({ failureKind: "deterministic", realOrderSent: false });
    expect(sharedFailureReport("execution", "run", false)).toMatchObject({ failureKind: "retryable", realOrderSent: null });
    expect(sharedFailureReport("execution", "run", true)).toMatchObject({ realOrderSent: false });
  });
  const preflight = [
    { accountId: "bad", status: "FAILED" as const, reason: "temporarily unavailable", actionCount: 0, maxActionNotionalUsd: 0 },
    { accountId: "good", status: "READY" as const, actionCount: 2, maxActionNotionalUsd: 125 }
  ];
  it("executes a ready account even when another preflight fails", async () => {
    const execute = vi.fn(async () => [{ accountId: "good", status: "FILLED_AND_ALIGNED", orderRequested: true }]);
    const result = await runPreflightedBatch(preflight, false, execute);
    expect(execute).toHaveBeenCalledWith(["good"]);
    expect(result.map(({ status }) => status)).toEqual(["FAILED", "FILLED_AND_ALIGNED"]);
  });
  it("never executes on no-submit and preserves failed preflight", async () => {
    const execute = vi.fn(); const result = await runPreflightedBatch(preflight, true, execute);
    expect(execute).not.toHaveBeenCalled(); expect(result.map(({ status }) => status)).toEqual(["FAILED", "PREFLIGHT_READY"]);
  });
  it("records preflight failure and isolates failed evidence recording", async () => {
    const execute = vi.fn(async () => [{ accountId: "good", status: "NO_ACTION", orderRequested: false }]);
    const recordFailure = vi.fn(async () => { throw new Error("database unavailable"); });
    const result = await runPreflightedBatch(preflight, false, execute, recordFailure);
    expect(recordFailure).toHaveBeenCalledWith(preflight[0]);
    expect(execute).toHaveBeenCalledWith(["good"]);
    expect(result[0]).toMatchObject({ evidenceRecordingFailed: true, failureKind: "retryable" });
  });
  it("missing owner cannot prevent another eligible account executing", async () => {
    const candidates = [{ accountId: "good", masterAddress: "other-wallet" }];
    const result = await runPreflightedBatch([preflight[1]], false, async () => [{ accountId: "good", status: "FILLED_AND_ALIGNED", orderRequested: true }]);
    expect(summarizeAccountBatch(candidates, result, "owner-wallet")).toMatchObject({ successful: false, ownerResult: { status: "BLOCKED" }, realOrderSent: true });
  });
  it("duplicate wallet enrollment blocks only that group", async () => {
    const candidates = [{ accountId: "bad", masterAddress: "owner-wallet" }, { accountId: "duplicate", masterAddress: "OWNER-WALLET" }, { accountId: "good", masterAddress: "independent" }];
    const isolated = isolateDuplicateWallets(candidates, [...preflight, { ...preflight[1], accountId: "duplicate" }]);
    const execute = vi.fn(async () => [{ accountId: "good", status: "NO_ACTION", orderRequested: false }]);
    const result = await runPreflightedBatch(isolated, false, execute);
    expect(execute).toHaveBeenCalledWith(["good"]);
    expect(summarizeAccountBatch(candidates, result, "owner-wallet").ownerResult.status).toBe("BLOCKED");
  });
  it("blocked entry reaches live recovery but cannot pass no-submit", async () => {
    const rows = [{ accountId: "flat", status: "ENTRY_BLOCKED" as const, reason: "entry margin is insufficient", failureKind: "deterministic" as const, actionCount: 0, maxActionNotionalUsd: 0 }];
    const execute = vi.fn(async () => [{ accountId: "flat", status: "ENTRY_FAILED_STAYING_CASH", orderRequested: false }]);
    expect(await runPreflightedBatch(rows, false, execute)).toMatchObject([{ status: "ENTRY_FAILED_STAYING_CASH" }]);
    expect(execute).toHaveBeenCalledWith(["flat"]);
    execute.mockClear();
    expect(await runPreflightedBatch(rows, true, execute)).toMatchObject([{ status: "PREFLIGHT_ENTRY_BLOCKED", orderRequested: false }]);
    expect(execute).not.toHaveBeenCalled();
  });
});
