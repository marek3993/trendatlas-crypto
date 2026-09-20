import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = (relativePath: string) => fs.readFileSync(path.join(process.cwd(), relativePath), "utf8");

describe("current strategy description", () => {
  it("documents the exact promoted strategy controls", () => {
    const page = source("src/app/strategy/page.tsx");
    expect(page).toContain("phase68g_etf_flow_impulse_early_risk_cooldown_15");
    expect(page).toContain("0.50× BTC exposure");
    expect(page).toContain("$500 million");
    expect(page).toContain("10-day EMA");
    expect(page).toContain("15-day cooldown");
    expect(page).toContain("D+1 contract");
  });

  it("separates model candidates, live targets and real account state", () => {
    const page = source("src/app/strategy/page.tsx");
    expect(page).toContain("candidate alone does not create a trade");
    expect(page).toContain("dashboard reads real exposure from Hyperliquid");
    expect(page).toContain("BTC, ETH or CASH");
  });

  it("loads only the signed-in user's latest execution run", () => {
    const page = source("src/app/strategy/page.tsx");
    expect(page).toContain('await requireUser()');
    expect(page).toContain('.eq("user_id", user.id)');
  });
});
