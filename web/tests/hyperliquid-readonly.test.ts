import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { normalizeHyperliquidAddress, validateHyperliquidAddress } from "@/lib/hyperliquid/address";

const webRoot = process.cwd();
const repositoryRoot = path.resolve(webRoot, "..");
const source = (relativePath: string) => fs.readFileSync(path.join(webRoot, relativePath), "utf8");
const migration = source("supabase/migrations/202609040002_create_hyperliquid_accounts.sql");
const infoClient = source("src/lib/hyperliquid/info.ts");
const onboardingAction = source("src/app/onboarding/actions.ts");
const dashboard = source("src/app/dashboard/page.tsx");
const connectForm = source("src/components/hyperliquid-connect-form.tsx");

function filesUnder(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(target) : [target];
  });
}

describe("Hyperliquid read-only onboarding", () => {
  it("accepts and normalizes a valid Hyperliquid address", () => {
    const input = "  0xAbCdEf0123456789aBCdEf0123456789aBcDeF01  ";
    expect(validateHyperliquidAddress(input)).toEqual({ ok: true, address: "0xabcdef0123456789abcdef0123456789abcdef01" });
    expect(normalizeHyperliquidAddress(input)).toBe("0xabcdef0123456789abcdef0123456789abcdef01");
  });

  it("rejects an invalid Hyperliquid address", () => {
    expect(validateHyperliquidAddress("0x1234")).toMatchObject({ ok: false });
    expect(validateHyperliquidAddress("not-an-address")).toMatchObject({ ok: false });
  });

  it("creates a read-only connection for the authenticated owner only", () => {
    expect(onboardingAction).toContain("const { user } = await requireUser()");
    expect(onboardingAction).toContain("user_id: user.id");
    expect(onboardingAction).toContain('connection_status: "read_only_connected"');
    expect(onboardingAction).toContain("verified_at:");
  });

  it("enforces cross-user RLS denial for every table operation", () => {
    expect(migration).toContain("enable row level security");
    expect(migration).toContain("force row level security");
    expect(migration).toContain("hyperliquid_accounts_select_own");
    expect(migration).toContain("hyperliquid_accounts_insert_own");
    expect(migration).toContain("hyperliquid_accounts_update_own");
    expect(migration).toContain("hyperliquid_accounts_delete_own");
    expect(migration.match(/auth\.uid\(\)\) = user_id/g)?.length).toBeGreaterThanOrEqual(5);
  });

  it("permits only the two required Info API request types", () => {
    expect(infoClient).toContain('ALLOWED_INFO_REQUEST_TYPES = ["clearinghouseState", "openOrders"]');
    expect(infoClient).toContain('method: "POST"');
    expect(infoClient).toContain("https://api.hyperliquid.xyz/info");
    expect(infoClient).toContain("withdrawableUsd");
    expect(infoClient).not.toContain("freeCollateralUsd");
  });

  it("fails closed before network access for an unknown Info request", () => {
    const guard = infoClient.indexOf("if (!isAllowedInfoRequestType(type)) throw new HyperliquidInfoError()");
    const request = infoClient.indexOf("response = await fetch");
    expect(guard).toBeGreaterThanOrEqual(0);
    expect(request).toBeGreaterThan(guard);
  });

  it("has no secret fields in the connection schema", () => {
    expect(migration).not.toMatch(/private|signer|secret|seed|trading_enabled/i);
  });

  it("has no secret input in the connection UI", () => {
    expect(connectForm).toContain('name="masterAddress"');
    expect(connectForm).not.toMatch(/password|private|seed|secret|signer/i);
  });

  it("does not import a Hyperliquid trading SDK", () => {
    const appSource = filesUnder(path.join(webRoot, "src")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    expect(appSource).not.toMatch(/from\s+["'][^"']*(hyperliquid-sdk|hyperliquid.*exchange|nktkas)[^"']*["']/i);
    expect(appSource).not.toMatch(/require\(["'][^"']*(hyperliquid-sdk|hyperliquid.*exchange|nktkas)[^"']*["']\)/i);
  });

  it("does not expose an order submitter from the web source", () => {
    const appSource = filesUnder(path.join(webRoot, "src")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    expect(appSource).not.toMatch(/marketOrder|limitOrder|submitOrder|cancelOrder|modifyOrder|transfer\s*\(|withdraw\s*\(|updateLeverage/i);
  });

  it("requires authentication for onboarding", () => {
    expect(source("src/app/onboarding/page.tsx")).toContain("await requireUser()");
    expect(source("src/proxy.ts")).toContain('"/onboarding"');
  });

  it("queries the dashboard with the logged-in user's account only", () => {
    expect(dashboard).toContain("const { supabase, user } = await requireUser()");
    expect(dashboard).toContain('.eq("user_id", user.id)');
    expect(dashboard).toContain("getHyperliquidAccountSnapshot(account.master_address)");
  });

  it("disconnects only the logged-in user's connection", () => {
    expect(onboardingAction).toContain('delete().eq("user_id", user.id)');
    expect(onboardingAction).not.toMatch(/formData\.get\([^)]*(id|user)/i);
  });

  it("does not copy the protected production address into web source", () => {
    const production = fs.readFileSync(path.join(repositoryRoot, "scripts/execution/run_trendatlas_production.py"), "utf8");
    const addresses = production.match(/0x[a-fA-F0-9]{40}/g) ?? [];
    const appSource = filesUnder(path.join(webRoot, "src")).map((file) => fs.readFileSync(file, "utf8")).join("\n");
    addresses.forEach((address) => expect(appSource).not.toContain(address));
  });

  it("leaves protected production paths unchanged", () => {
    const output = execFileSync(
      "git",
      ["diff", "--name-only", "--", "scripts/execution/run_trendatlas_production.py", "deploy/systemd/mrv1-production.service", "deploy/systemd/mrv1-production.timer"],
      { cwd: repositoryRoot, encoding: "utf8" }
    );
    expect(output.trim()).toBe("");
  });
});
