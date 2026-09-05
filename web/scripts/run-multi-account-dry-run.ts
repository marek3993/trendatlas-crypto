import path from "node:path";
import { fileURLToPath } from "node:url";

const mode = process.env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE;

if (mode !== "dry_run") {
  console.error(
    "Refused: TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE must equal dry_run."
  );
  process.exit(1);
}

async function main(): Promise<void> {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
  const webRoot = path.resolve(scriptDirectory, "..");
  const repositoryRoot = path.resolve(webRoot, "..");

  const [
    { HyperliquidDryRunGateway },
    { SupabaseExecutionRepository },
    { runEligibleAccountsOnce }
  ] = await Promise.all([
    import("@/server/multi-account-executor/dry-run-gateway"),
    import("@/server/multi-account-executor/repository"),
    import("@/server/multi-account-executor/worker")
  ]);

  const results = await runEligibleAccountsOnce(
    repositoryRoot,
    new SupabaseExecutionRepository(),
    new HyperliquidDryRunGateway()
  );

  console.log(JSON.stringify({
    mode: "dry_run",
    results
  }, null, 2));

  if (results.some(({ status }) =>
    status === "FAILED" ||
    status === "UNKNOWN_SUBMISSION_STATE"
  )) {
    process.exitCode = 1;
  }
}

void main().catch((error) => {
  const message = error instanceof Error ? error.message : "Unknown dry-run error.";
  console.error(`Multi-account dry run failed safely: ${message}`);
  process.exitCode = 1;
});
