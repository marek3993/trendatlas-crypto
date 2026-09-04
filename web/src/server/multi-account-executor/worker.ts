import "server-only";

import { loadAuthorizedTarget } from "./authority";
import { MultiAccountExecutor, type AccountResult, type ExchangeGateway, type ExecutionRepository } from "./engine";
import { executionMode } from "./mode";

/** Worker-only entry point. Scheduling and HTTP routes are intentionally absent. */
export async function runEligibleAccountsOnce(repositoryRoot: string, repository: ExecutionRepository, exchange: ExchangeGateway): Promise<AccountResult[]> {
  const target = await loadAuthorizedTarget(repositoryRoot);
  return new MultiAccountExecutor(repository, exchange, executionMode()).runAllForTarget(target);
}
