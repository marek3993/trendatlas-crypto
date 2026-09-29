import fs from "node:fs/promises";
import { buildPlan } from "@/server/multi-account-executor/planner";
import type { AccountState, AuthorizedTarget, MarketSpec } from "@/server/multi-account-executor/types";
async function main() {
  const input = JSON.parse(await fs.readFile(process.argv[2], "utf8")) as {
    target: AuthorizedTarget; markets: [string, MarketSpec][]; accounts: { account: AccountState }[];
  };
  const plans = input.accounts.map(({account}) => buildPlan(input.target, account, new Map(input.markets)));
  await fs.writeFile(process.argv[3], JSON.stringify({ target: input.target, plans }) + "\n", { mode: 0o600 });
}
void main().catch(() => { console.error("Golden replay failed"); process.exitCode=1; });
