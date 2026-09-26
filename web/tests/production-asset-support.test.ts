import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { deriveProductionTargets, parseProductionCsv, verifyProductionAssetSupport, verifyProductionUniverseSources } from "../src/server/multi-account-executor/asset-support";
import type { MarketSpec } from "../src/server/multi-account-executor/types";

const header = "date,strategy_version,execution_target_asset,execution_target_exposure,source_validated";
const snapshot = { strategy_version: "fixture", closed_day: "2026-09-24", validation: { status: "passed" }, execution_intent: { target_asset: "AVAX", target_exposure: 1.25, stale_signal: false } };
const csv = `${header}\n2026-09-22,fixture,CASH,0,True\n2026-09-23,fixture,BTC,0.49,True\n2026-09-24,fixture,AVAX,1.25,True\n`;
const markets = new Map<string, MarketSpec>([
  ["BTC", { asset: "BTC", markPrice: 100000, sizeDecimals: 5, minNotionalUsd: 10 }],
  ["AVAX", { asset: "AVAX", markPrice: 25, sizeDecimals: 2, minNotionalUsd: 10 }],
  ["NEWCOIN", { asset: "NEWCOIN", markPrice: 1.25, sizeDecimals: 3, minNotionalUsd: 10 }],
]);

describe("production deployment assets are derived from strategy data", () => {
  it("plans every emitted target from cash, each emitted position and another supported position", () => {
    expect(verifyProductionAssetSupport(deriveProductionTargets(csv, snapshot), markets)).toEqual({ assets: ["AVAX", "BTC", "CASH"], planCount: 12, unsupportedAssets: [] });
  });
  it("supports a new strategy asset without editing any executor source", () => {
    const updated = csv.replaceAll("AVAX", "NEWCOIN");
    const targets = deriveProductionTargets(updated, { ...snapshot, execution_intent: { ...snapshot.execution_intent, target_asset: "NEWCOIN" } });
    expect(verifyProductionAssetSupport(targets, markets).assets).toContain("NEWCOIN");
  });
  it("reports unsupported entry without blocking old-position exits", () => {
    const targets = deriveProductionTargets(csv.replaceAll("AVAX", "UNLISTED"), { ...snapshot, execution_intent: { ...snapshot.execution_intent, target_asset: "UNLISTED" } });
    expect(verifyProductionAssetSupport(targets, markets).unsupportedAssets).toEqual(["UNLISTED"]);
  });
  it("does not silently whitelist historical synthetic execution targets", () => {
    const targets = deriveProductionTargets(csv.replaceAll("BTC", "BASE"), snapshot);
    expect(() => verifyProductionAssetSupport(targets, markets)).toThrow(/Concrete strategy asset/);
  });
  it("uses the adapter current selector contract rather than stitched historical basket labels", () => {
    const current = { ...snapshot, source_inputs: { current_emittable_universe: {
      schema_version: 1, status: "available", source_kind: "current_production_selector", strategy_version: "fixture", closed_day: snapshot.closed_day,
      assets: ["BTC", "AVAX", "CASH", "NEWCOIN"], selector_sha256: "a".repeat(64), adapter_sha256: "b".repeat(64),
    } } };
    const targets = deriveProductionTargets(csv.replaceAll("BTC", "BASE"), current);
    expect(verifyProductionAssetSupport(targets, markets).assets).toEqual(["AVAX", "BTC", "CASH", "NEWCOIN"]);
    expect(() => deriveProductionTargets(csv, { ...current, execution_intent: { ...snapshot.execution_intent, target_asset: "BASE" } })).toThrow(/does not belong/);
    expect(() => deriveProductionTargets(csv, { ...current, source_inputs: { current_emittable_universe: { ...current.source_inputs.current_emittable_universe, status: "unavailable" } } })).toThrow(/unavailable/);
  });
  it("rejects empty, invalid, unvalidated and mismatched source files", () => {
    for (const invalid of ["", header, csv.replace("0.49", "NaN"), csv.replace("True", "False"), csv.replace("fixture,CASH", "other,CASH"), csv.replace("2026-09-24", "2026-09-25")]) {
      expect(() => deriveProductionTargets(invalid, snapshot)).toThrow();
    }
    expect(() => deriveProductionTargets(csv, { ...snapshot, validation: { status: "failed" } })).toThrow();
    expect(() => verifyProductionAssetSupport([], markets)).toThrow();
    expect(() => verifyProductionAssetSupport(deriveProductionTargets(csv, snapshot), new Map())).toThrow();
  });
  it("parses quoted metadata without corrupting the target columns", () => {
    expect(parseProductionCsv('a,b\n"comma, and ""quote""","multiple\nlines"\n')).toEqual([{ a: 'comma, and "quote"', b: 'multiple\nlines' }]);
    expect(() => parseProductionCsv('a,b\n"unterminated,b')).toThrow();
  });
  it("binds the universe to fresh selector data and the exact deployed adapter", () => {
    const selector = "asset,end_date,history_days\nAVAX,2026-09-24,180\nNEWCOIN,2026-09-24,300\n";
    const adapter = "# Fixture adapter source\n";
    const hash = (value: string) => createHash("sha256").update(value).digest("hex");
    const contract = { selector_source: "selector.csv", adapter_source: "adapter.py" };
    const universe = { ...contract, status: "available", assets: ["AVAX", "NEWCOIN", "BTC", "CASH"], overlay_assets: ["BTC"], selector_candidate_count: 2, selector_sha256: hash(selector), adapter_sha256: hash(adapter) };
    const current = { ...snapshot, source_inputs: { current_emittable_universe: universe } };
    expect(() => verifyProductionUniverseSources(current, contract, selector, adapter)).not.toThrow();
    expect(() => verifyProductionUniverseSources(current, contract, selector, `${adapter}# changed`)).toThrow(/fingerprints/);
    expect(() => verifyProductionUniverseSources(current, contract, `${selector}BTC,2026-09-24,180\n`, adapter)).toThrow(/fingerprints/);
    const changed = (patch: Record<string, unknown>) => ({ ...current, source_inputs: { current_emittable_universe: { ...universe, ...patch } } });
    expect(() => verifyProductionUniverseSources(changed({ assets: [...universe.assets, "UNLISTED"] }), contract, selector, adapter)).toThrow(/differs/);
    expect(() => verifyProductionUniverseSources(changed({ selector_source: "other.csv" }), contract, selector, adapter)).toThrow(/paths/);
    const stale = selector.replaceAll("2026-09-24", "2026-09-23");
    expect(() => verifyProductionUniverseSources(changed({ selector_sha256: hash(stale) }), contract, stale, adapter)).toThrow(/stale/);
    expect(() => verifyProductionUniverseSources(snapshot, contract, selector, adapter)).toThrow(/missing/);
  });
});
