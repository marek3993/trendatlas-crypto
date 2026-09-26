import { createHash } from "node:crypto";
import { buildPlan } from "./planner";
import { normalizeTargetAsset, type AuthorizedTarget, type MarketSpec } from "./types";

/** Strict CSV reader: quoted cells and embedded newlines are supported. */
export function parseProductionCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false, closedQuote = false;
  const content = text.replace(/^\uFEFF/, "");
  for (let index = 0; index < content.length; index += 1) {
    const value = content[index];
    if (quoted) {
      if (value === '"' && content[index + 1] === '"') { cell += '"'; index += 1; }
      else if (value === '"') { quoted = false; closedQuote = true; }
      else cell += value;
    } else if (value === '"') {
      if (cell || closedQuote) throw new Error("Production CSV quote is invalid.");
      quoted = true;
    } else if (value === ",") {
      row.push(cell); cell = ""; closedQuote = false;
    } else if (value === "\n" || value === "\r") {
      if (value === "\r" && content[index + 1] === "\n") index += 1;
      row.push(cell); rows.push(row); row = []; cell = ""; closedQuote = false;
    } else {
      if (closedQuote) throw new Error("Production CSV trailing quoted data is invalid.");
      cell += value;
    }
  }
  if (quoted) throw new Error("Production CSV has an unterminated quote.");
  if (cell || row.length || closedQuote) { row.push(cell); rows.push(row); }
  const headers = rows.shift();
  if (!headers?.length || new Set(headers).size !== headers.length || headers.some((header) => !header)) throw new Error("Production CSV header is invalid.");
  if (!rows.length) throw new Error("Production CSV has no observations.");
  return rows.map((values) => {
    if (values.length !== headers.length) throw new Error("Production CSV row has invalid width.");
    return Object.fromEntries(headers.map((header, index) => [header, values[index]]));
  });
}

export function deriveProductionTargets(csv: string, snapshotValue: unknown): AuthorizedTarget[] {
  if (!snapshotValue || typeof snapshotValue !== "object") throw new Error("Production snapshot is missing.");
  const snapshot = snapshotValue as Record<string, unknown>;
  const intent = snapshot.execution_intent as Record<string, unknown> | undefined;
  const validation = snapshot.validation as Record<string, unknown> | undefined;
  if (validation?.status !== "passed" || !intent || intent.stale_signal !== false || typeof snapshot.strategy_version !== "string") throw new Error("Production snapshot is not validated.");
  const targets = new Map<string, AuthorizedTarget>();
  const add = (assetValue: unknown, exposureValue: unknown, dayValue: unknown, validated: boolean) => {
    const asset = normalizeTargetAsset(assetValue);
    const exposure = typeof exposureValue === "string" && exposureValue.trim() ? Number(exposureValue) : exposureValue;
    const day = typeof dayValue === "string" ? dayValue : "";
    if (!validated || !asset || typeof exposure !== "number" || !Number.isFinite(exposure) || (asset === "CASH" ? exposure !== 0 : exposure <= 0) || !/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day))) throw new Error("Production target observation is invalid.");
    targets.set(`${asset}:${exposure}`, { asset, exposure, closedDay: day, signalId: `deployment-check:${asset}:${exposure}`,
      strategyVersion: snapshot.strategy_version as string, stale: false, executionGate: asset === "CASH" ? "no_action" : "approved" });
  };
  let previousDay = "";
  for (const row of parseProductionCsv(csv)) {
    if (!row.date || row.date <= previousDay || row.strategy_version !== snapshot.strategy_version) throw new Error("Production timeseries chronology or strategy provenance is invalid.");
    previousDay = row.date;
    add(row.execution_target_asset, row.execution_target_exposure, row.date, row.source_validated?.toLowerCase() === "true");
  }
  if (previousDay !== snapshot.closed_day) throw new Error("Production snapshot and timeseries days differ.");
  const sourceInputs = snapshot.source_inputs as Record<string, unknown> | undefined;
  const universe = sourceInputs?.current_emittable_universe as Record<string, unknown> | undefined;
  if (universe?.source_kind === "resolved_strategy_routes_with_price_data") {
    if (universe.status !== "available" || universe.closed_day !== snapshot.closed_day || universe.strategy_version !== snapshot.strategy_version || !Array.isArray(universe.assets) || !universe.assets.includes(intent.target_asset)) throw new Error("Resolved production instrument universe is invalid.");
    for (const row of parseProductionCsv(csv)) {
      if (row.resolved_execution_asset !== row.execution_target_asset || !universe.assets.includes(row.resolved_execution_asset) || ["BASE", "BASELINE", "CANDIDATE", "ALT"].includes(row.resolved_execution_asset)) throw new Error("Resolved route asset differs from execution target.");
    }
  } else if (universe) {
    if (universe.status !== "available" || universe.source_kind !== "current_production_selector" || universe.closed_day !== snapshot.closed_day || universe.strategy_version !== snapshot.strategy_version || !Array.isArray(universe.assets) || universe.assets.length === 0 || !/^[a-f0-9]{64}$/.test(String(universe.selector_sha256)) || !/^[a-f0-9]{64}$/.test(String(universe.adapter_sha256))) throw new Error("Current production instrument universe is unavailable or invalid.");
    const assets = universe.assets.map(normalizeTargetAsset);
    if (assets.some((asset) => !asset) || new Set(assets).size !== assets.length || !assets.includes(normalizeTargetAsset(intent.target_asset))) throw new Error("Current target does not belong to its validated production instrument universe.");
    const exposures = new Set([...targets.values()].filter((target) => target.asset !== "CASH").map((target) => target.exposure));
    if (typeof intent.target_exposure === "number" && intent.target_exposure > 0) exposures.add(intent.target_exposure);
    if (!exposures.size && assets.some((asset) => asset !== "CASH")) throw new Error("Production instrument universe has no validated market exposure evidence.");
    targets.clear();
    for (const asset of assets) {
      for (const exposure of asset === "CASH" ? [0] : exposures) add(asset, exposure, snapshot.closed_day, true);
    }
  }
  add(intent.target_asset, intent.target_exposure, snapshot.closed_day, true);
  return [...targets.values()];
}

/** Verify deployment capability evidence against the declared production sources. */
export function verifyProductionUniverseSources(snapshotValue: unknown, contractValue: unknown, selectorText: string, adapterText: string): void {
  const snapshot = snapshotValue as Record<string, unknown> | null;
  const contract = contractValue as Record<string, unknown> | null;
  const inputs = snapshot?.source_inputs as Record<string, unknown> | undefined;
  const universe = inputs?.current_emittable_universe as Record<string, unknown> | undefined;
  if (!snapshot || !contract || !universe || universe.status !== "available" || !Array.isArray(universe.assets) || !Array.isArray(universe.overlay_assets) || !selectorText.trim() || !adapterText.trim()) throw new Error("Current production instrument universe source evidence is missing.");
  if (universe.selector_source !== contract.selector_source || universe.adapter_source !== contract.adapter_source) throw new Error("Current production instrument universe source paths differ from its contract.");
  const hash = (text: string) => createHash("sha256").update(text).digest("hex");
  if (universe.selector_sha256 !== hash(selectorText) || universe.adapter_sha256 !== hash(adapterText)) throw new Error("Current production instrument universe source fingerprints do not match the deployed files.");
  const candidates = parseProductionCsv(selectorText);
  const assets = new Set<string>();
  for (const row of candidates) {
    const asset = normalizeTargetAsset(row.asset);
    const endDay = row.end_date?.slice(0, 10);
    if (!asset || assets.has(asset) || !/^\d{4}-\d{2}-\d{2}$/.test(endDay ?? "") || !Number.isFinite(Date.parse(endDay)) || endDay < String(snapshot.closed_day) || !Number.isInteger(Number(row.history_days)) || Number(row.history_days) <= 0) throw new Error("Current production selector candidate evidence is invalid or stale.");
    assets.add(asset);
  }
  if (universe.selector_candidate_count !== candidates.length) throw new Error("Current production selector candidate count differs from its source.");
  for (const value of universe.overlay_assets) {
    const asset = normalizeTargetAsset(value);
    if (!asset) throw new Error("Current production overlay asset is invalid.");
    assets.add(asset);
  }
  assets.add("CASH");
  if (JSON.stringify([...assets].sort()) !== JSON.stringify([...universe.assets].sort())) throw new Error("Current production instrument universe differs from its selector and overlay sources.");
}

/** Route-era universe is proved by BASE/governance and same-symbol prices, never a candidate drop list. */
export function verifyCausalProductionUniverse(snapshotValue: unknown, contractValue: unknown, sources: Record<string, string>): void {
  const snapshot = snapshotValue as Record<string, unknown>;
  const contract = contractValue as Record<string, unknown>;
  const inputs = snapshot.source_inputs as Record<string, unknown>;
  const universe = inputs.current_emittable_universe as Record<string, unknown>;
  const files = inputs.files as Record<string, { path: string; sha256: string }>;
  if (universe.source_kind !== "resolved_strategy_routes_with_price_data" || universe.status !== "available") throw new Error("Resolved route universe is missing.");
  for (const value of Object.values(files)) {
    if (typeof sources[value.path] !== "string" || createHash("sha256").update(sources[value.path]).digest("hex") !== value.sha256) throw new Error("Route input fingerprint differs from source.");
  }
  const normalize = (value: string) => normalizeTargetAsset(value.replace(/USDT$/, ""));
  const base = parseProductionCsv(sources[String(contract.base_source)]);
  const governance = parseProductionCsv(sources[String(contract.selector_source)]);
  if (base.at(-1)?.ts !== snapshot.closed_day || governance.at(-1)?.date !== snapshot.closed_day) throw new Error("Route universe inputs are stale.");
  const assets = new Set(["BTC", "CASH"]);
  for (const row of base) {
    const coin = normalize(row.selected);
    if (!coin) throw new Error("BASE economic holding is invalid.");
    assets.add(coin);
  }
  for (const row of governance) if (row.executed_regime === "CANDIDATE") {
    const coin = normalize(row.executed_position);
    if (!coin || coin !== normalize(row.chosen_asset)) throw new Error("Candidate trigger identity differs.");
    assets.add(coin);
  }
  for (const coin of assets) if (coin !== "CASH") {
    const rows = parseProductionCsv(sources[`data/ohlcv/${coin}USDT_1d.csv`]);
    const current = rows.find((row) => row.date === snapshot.closed_day);
    if (!current || !(Number(current.close) > 0) || !(Number(current.open) > 0)) throw new Error("Route price evidence is missing.");
  }
  if (!Array.isArray(universe.assets) || JSON.stringify([...assets].sort()) !== JSON.stringify([...universe.assets].sort())) throw new Error("Route universe differs from economic sources.");
}

export function verifyProductionAssetSupport(targets: AuthorizedTarget[], markets: Map<string, MarketSpec>): { assets: string[]; planCount: number; unsupportedAssets: string[] } {
  if (!targets.length || !markets.size) throw new Error("Production targets and exchange metadata must not be empty.");
  const assets = [...new Set(targets.map((target) => target.asset))].sort();
  if (assets.some((asset) => ["BASE", "BASELINE", "CANDIDATE", "ALT"].includes(asset))) throw new Error("Concrete strategy asset required.");
  const unsupportedAssets = assets.filter((asset) => asset !== "CASH" && !markets.has(asset));
  const tradable = assets.filter((asset) => asset !== "CASH" && markets.has(asset));
  // Each possible current strategy position, plus an arbitrary exchange-supported
  // position, must reconcile to every target without adding an executor asset list.
  const arbitrary = [...markets.keys()].find((asset) => !tradable.includes(asset)) ?? [...markets.keys()][0];
  const currentAssets = [...new Set(["CASH", ...tradable, arbitrary])];
  let planCount = 0;
  for (const target of targets) {
    const targetMarket = markets.get(target.asset);
    const exposure = target.exposure || 1;
    const equity = Math.max(100_000, targetMarket ? 1000 * Math.max(targetMarket.minNotionalUsd, targetMarket.markPrice * 10 ** -targetMarket.sizeDecimals) / exposure : 0);
    for (const current of currentAssets) {
      const market = markets.get(current);
      const size = market ? Math.max(1, Math.floor(equity * 0.49 / market.markPrice * 10 ** market.sizeDecimals)) / 10 ** market.sizeDecimals : 0;
      const plan = buildPlan(target, { equityUsd: equity, positions: current === "CASH" ? [] : [{ asset: current, size, markPrice: market!.markPrice }], openOrderCount: 0, openOrders: [] }, markets);
      if (unsupportedAssets.includes(target.asset)) {
        if (!(plan.entryBlockedReason || plan.reason) || (current !== "CASH" && !plan.actions.some((action) => action.asset === current && action.reduceOnly))) throw new Error("Unsupported entry must preserve a supported old-position exit.");
        planCount += 1;
        continue;
      }
      if (plan.state === "BLOCKED" || plan.entryBlockedReason || (target.asset !== "CASH" && !plan.actions.some((action) => action.asset === target.asset && ["ENTER", "RESIZE"].includes(action.action)) && plan.state !== "NO_ACTION")) throw new Error(`Strategy deployment rejected: ${current} -> ${target.asset} ${target.exposure}x has no valid plan (${plan.reason ?? plan.entryBlockedReason ?? plan.state}).`);
      planCount += 1;
    }
  }
  return { assets, planCount, unsupportedAssets };
}
