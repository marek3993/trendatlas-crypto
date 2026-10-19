import "server-only";

import { loadCleanTarget } from "./clean-authority";
import path from "node:path";
import { MultiAccountExecutor, type AccountResult, type ExchangeGateway, type ExecutionRepository } from "./engine";
import { executionMode } from "./mode";

/** Worker-only entry point. Scheduling and HTTP routes are intentionally absent. */
export async function runEligibleAccountsOnce(stateDirectory: string, repository: ExecutionRepository, exchange: ExchangeGateway): Promise<AccountResult[]> {
  const target = await loadCleanTarget(path.join(stateDirectory,"signal.json"));
  return new MultiAccountExecutor(repository, exchange, executionMode()).runAllForTarget(target);
}
