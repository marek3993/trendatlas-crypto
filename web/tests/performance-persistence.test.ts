import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = (relativePath: string) => fs.readFileSync(path.join(process.cwd(), relativePath), "utf8");

describe("automatic account performance persistence", () => {
  it("keeps persistence server-only and stores current plus daily history", () => {
    const store = source("src/lib/hyperliquid/performance-store.ts");
    expect(store).toMatch(/^import "server-only";/);
    expect(store).toContain('from("hyperliquid_account_performance")');
    expect(store).toContain('from("hyperliquid_account_performance_history")');
    expect(store).toContain('onConflict: "hyperliquid_account_id,performance_day"');
  });

  it("persists a successful live dashboard calculation automatically", () => {
    const page = source("src/app/dashboard/page.tsx");
    expect(page).toContain("persistHyperliquidAccountPerformance");
    expect(page).toContain("Performance persistence must never hide fresh exchange data");
  });
});
