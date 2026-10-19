import path from "node:path";
import { fileURLToPath } from "node:url";

const mode = process.env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE;

if (mode !== "dry_run") {
  console.error("Refused: live preflight requires exact dry_run mode.");
  process.exit(1);
}

async function main(): Promise<void> {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
  const webRoot = path.resolve(scriptDirectory, "..");
  const repositoryRoot = path.resolve(webRoot, "..");
  const [
    { HyperliquidLiveGateway },
    { runMultiAccountLivePreflight },
    { SupabaseExecutionRepository }
  ] = await Promise.all([
    import("@/server/multi-account-executor/hyperliquid-live-gateway"),
    import("@/server/multi-account-executor/live-preflight"),
    import("@/server/multi-account-executor/repository")
  ]);
  const report = await runMultiAccountLivePreflight(
    repositoryRoot,
    new SupabaseExecutionRepository(),
    new HyperliquidLiveGateway()
  );
  console.log(JSON.stringify({ mode: "dry_run", exchangeWrites: 0, ...report }, null, 2));
  if (report.results.length === 0 || report.results.some(({ status }) => status === "BLOCKED" || status === "FAILED")) {
    process.exitCode = 1;
  }
}

void main().catch(() => {
  console.error("Multi-account live preflight failed safely.");
  process.exitCode = 1;
});
