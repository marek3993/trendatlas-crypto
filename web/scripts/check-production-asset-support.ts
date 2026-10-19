import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { deriveProductionTargets, verifyProductionAssetSupport, verifyProductionUniverseSources } from "@/server/multi-account-executor/asset-support";

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.some((value, index) => index % 2 === 0 ? value !== "--repository-root" : !value) || args.length > 2 || args.length % 2 !== 0) throw new Error("Usage: check-production-asset-support.ts [--repository-root PATH]");
  const root = path.resolve(args[1] || "..");
  const [series, snapshot, universeContractText] = await Promise.all([
    readFile(path.join(root, "outputs/production/current_strategy_timeseries.csv"), "utf8"),
    readFile(path.join(root, "outputs/production/current_strategy_snapshot.json"), "utf8"),
    readFile(path.join(root, "source_of_truth/production_asset_universe_contract.json"), "utf8")
  ]);
  const universeContract = JSON.parse(universeContractText) as Record<string, unknown>;
  const sourcePath = (key: string): string => {
    if (typeof universeContract[key] !== "string" || !universeContract[key]) throw new Error(`Missing ${key} in production instrument universe source contract.`);
    const resolved = path.resolve(root, universeContract[key]);
    const relative = path.relative(root, resolved);
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Production instrument universe source must remain inside the repository.");
    return resolved;
  };
  const [selector, adapter] = await Promise.all([readFile(sourcePath("selector_source"), "utf8"), readFile(sourcePath("adapter_source"), "utf8")]);
  const snapshotValue = JSON.parse(snapshot);
  verifyProductionUniverseSources(snapshotValue, universeContract, selector, adapter);
  const targets = deriveProductionTargets(series, snapshotValue);
  const { HyperliquidDryRunGateway } = await import("@/server/multi-account-executor/dry-run-gateway");
  const result = verifyProductionAssetSupport(targets, await new HyperliquidDryRunGateway().readMarkets());
  console.log(JSON.stringify({ status: "passed", ...result, metadataSource: "Hyperliquid metaAndAssetCtxs", snapshotSha256: createHash("sha256").update(snapshot).digest("hex"), timeseriesSha256: createHash("sha256").update(series).digest("hex"), exchangeWrites: false }, null, 2));
}

void main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "Production asset-support validation failed.");
  process.exitCode = 1;
});
