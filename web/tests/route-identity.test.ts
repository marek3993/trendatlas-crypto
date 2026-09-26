import { describe, expect, it, vi } from "vitest";
import { validateResolvedRoute } from "../src/server/multi-account-executor/route-identity";
import { runPreflightedBatch } from "../src/server/multi-account-executor/batch";
import type { LivePreflightResult } from "../src/server/multi-account-executor/live-preflight";

describe("production route boundary", () => {
  const sample = () => {
    const lineage = { route_type: "BASE", base_economic_asset: "LTC", candidate_asset: "AVAX",
      candidate_trigger_active: false, resolved_execution_asset: "LTC", resolution_reason: "same_interval_base_holding",
      signal_available_at: "2026-09-25T12:00:00Z" };
    const intent = { ...lineage, target_asset: "LTC", target_exposure: 1.25 };
    return { intent, production: { ...lineage, current_asset: "LTC", actual_held_asset: "LTC", closed_day: "2026-09-24", execution_intent: { ...intent } } };
  };
  it("retains BASE identity even when a weekly candidate differs", () => {
    const { production, intent } = sample();
    expect(() => validateResolvedRoute(production, intent)).not.toThrow();
  });
  it("rejects candidate label substituted after the validated build", () => {
    const { production, intent } = sample();
    intent.target_asset = "AVAX";
    expect(() => validateResolvedRoute(production, intent)).toThrow();
  });
  it("rejects missing route lineage", () => {
    const { production, intent } = sample();
    expect(() => validateResolvedRoute({ ...production, route_type: undefined }, intent)).toThrow();
  });
  it("no-submit never runs exchange or database mutation callbacks, including blocked entries", async () => {
    const execute = vi.fn(); const write = vi.fn();
    const rows = ["READY", "BLOCKED", "FAILED", "ENTRY_BLOCKED"].map((status, i) => ({ accountId: String(i), status, actions: [], actionCount: 0 })) as LivePreflightResult[];
    const result = await runPreflightedBatch(rows, true, execute, write);
    expect(result).toHaveLength(4);
    expect(execute).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
    expect(result.every((row) => row.orderRequested === false)).toBe(true);
  });
});
