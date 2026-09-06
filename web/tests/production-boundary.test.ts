import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const repositoryRoot = path.resolve(process.cwd(), "..");
const protectedFiles = [
  "scripts/execution/run_trendatlas_production.py",
  "deploy/systemd/mrv1-production.service",
  "deploy/systemd/mrv1-production.timer"
];

function filesUnder(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(target) : [target];
  });
}

function gitDiffNames(paths: string[]): string[] {
  const output = execFileSync("git", ["diff", "--name-only", "--", ...paths], { cwd: repositoryRoot, encoding: "utf8" });
  return output.split(/\r?\n/).filter(Boolean);
}

const webSourceDirectory = path.join(process.cwd(), "src");
const sourceFiles = filesUnder(webSourceDirectory);
const sourceText = (file: string) => fs.readFileSync(file, "utf8");
const allWebSource = sourceFiles.map(sourceText).join("\n");
const clientModules = sourceFiles.filter((file) => /^\s*["']use client["']/.test(sourceText(file)));
const clientSource = clientModules.map(sourceText).join("\n");
const appSource = filesUnder(path.join(webSourceDirectory, "app")).map(sourceText).join("\n");
const agentAuthorizationModule = source("lib/hyperliquid/agent-authorization.ts");
const adminModule = source("lib/supabase/admin.ts");
const liveGatewayModule = source("server/multi-account-executor/hyperliquid-live-gateway.ts");
const liveGuardModule = source("server/multi-account-executor/exclusive-live-guard.ts");
const canonicalGuardModule = source("server/multi-account-executor/canonical-production-guard.ts");
const liveOnceRunner = fs.readFileSync(path.join(process.cwd(), "scripts/run-multi-account-live-once.ts"), "utf8");
const productionRunner = fs.readFileSync(path.join(process.cwd(), "scripts/run-multi-account-production-cycle.ts"), "utf8");
const packageJson = source("../package.json");

function source(relativePath: string): string {
  return fs.readFileSync(path.join(webSourceDirectory, relativePath), "utf8");
}

describe("production isolation boundary", () => {
  it("keeps production execution code unreachable from the web source", () => {
    expect(allWebSource).not.toMatch(/scripts\/execution|run_trendatlas_production|live[_-]?order|submit[_-]?order/i);
  });

  it("keeps the server-only order gateway unreachable from browser and request routes", () => {
    expect(liveGatewayModule).toMatch(/^import "server-only";/);
    expect(clientSource).not.toContain("hyperliquid-live-gateway");
    expect(appSource).not.toContain("hyperliquid-live-gateway");
    expect(packageJson).not.toContain('"multi-account:live"');
  });

  it("requires exclusive legacy shutdown, an account allowlist, signal confirmation, and a notional cap", () => {
    expect(liveGuardModule).toContain('readSystemdState("is-enabled", "mrv1-production.timer") !== "disabled"');
    expect(liveGuardModule).toContain('readSystemdState("is-active", "mrv1-production.timer") !== "inactive"');
    expect(liveGuardModule).toContain('readSystemdState("is-active", "mrv1-production.service") !== "inactive"');
    expect(liveOnceRunner).toContain("candidates.length !== 1");
    expect(liveOnceRunner).toContain("TRENDATLAS_LIVE_SIGNAL_CONFIRMATION !== target.signalId");
    expect(liveOnceRunner).toContain("maxActionNotionalUsd > guard.maxNotionalUsd");
    expect(liveOnceRunner).toContain("maxActionNotionalUsd: guard.maxNotionalUsd");
    expect(packageJson).toContain("flock --nonblock ../outputs/execution/production_runs/trendatlas_production.lock");
  });

  it("keeps browser modules free of wallet-secret inputs and secret identifiers", () => {
    expect(clientSource).not.toMatch(/name\s*=\s*["'][^"']*(private|seed|mnemonic|secret)[^"']*["']/i);
    expect(clientSource).not.toMatch(/(?:privateKey|private_key|encryptedPrivateKey|encrypted_private_key|service[_-]?role|SUPABASE_ADMIN_KEY|TRENDATLAS_AGENT_KEK_B64)/);
    expect(clientSource).not.toMatch(/(?:formData|FormData)\.get\([^)]*(private|seed|mnemonic|secret)/i);
  });

  it("keeps agent key handling server-only and excludes its secret helper from client modules", () => {
    expect(agentAuthorizationModule).toMatch(/^import "server-only";/);
    expect(adminModule).toMatch(/^import "server-only";/);
    clientModules.forEach((file) => {
      const contents = sourceText(file);
      expect(contents).not.toMatch(/from\s+["'][^"']*agent-authorization[^"']*["']/);
      expect(contents).not.toMatch(/from\s+["'][^"']*supabase\/admin[^"']*["']/);
    });
  });

  it("never accepts a master-wallet secret and never publishes an admin credential", () => {
    expect(allWebSource).not.toMatch(/(?:master|wallet|user)[A-Za-z_]*\s*(?:privateKey|private_key|seedPhrase|seed_phrase|mnemonic)/i);
    expect(allWebSource).not.toMatch(/process\.env\.NEXT_PUBLIC_[A-Z0-9_]*(?:ADMIN|SERVICE|SECRET|KEK|PRIVATE)/);
    expect(source("../.env.example")).not.toMatch(/^NEXT_PUBLIC_[A-Z0-9_]*(?:ADMIN|SERVICE|SECRET|KEK|PRIVATE)/m);
  });

  it("does not copy a protected account address from production code", () => {
    const protectedSource = fs.readFileSync(path.join(repositoryRoot, protectedFiles[0]), "utf8");
    const addresses = protectedSource.match(/0x[a-fA-F0-9]{40}/g) ?? [];
    addresses.forEach((address) => expect(allWebSource).not.toContain(address));
  });

  it("keeps the approved cutover inside the existing canonical service and timer", () => {
    const service = fs.readFileSync(path.join(repositoryRoot, protectedFiles[1]), "utf8");
    const timer = fs.readFileSync(path.join(repositoryRoot, protectedFiles[2]), "utf8");
    expect(service).toContain("MRV1_EXECUTION_BACKEND=multi_account");
    expect(service).toContain("run_trendatlas_production.py");
    expect(service).not.toContain("LoadCredentialEncrypted=hyperliquid-agent-private-key");
    expect(timer).toContain("Unit=mrv1-production.service");
  });

  it("binds production execution to the canonical run, owner account, and sequential batch", () => {
    expect(canonicalGuardModule).toMatch(/^import "server-only";/);
    expect(canonicalGuardModule).toContain('TRENDATLAS_MULTI_ACCOUNT_EXECUTION_CONTEXT !== "canonical_orchestrator"');
    expect(canonicalGuardModule).toContain("MRV1_CURRENT_AUTHORITY_RUN_ID");
    expect(canonicalGuardModule).toContain("MRV1_HYPERLIQUID_ACCOUNT_ADDRESS");
    expect(canonicalGuardModule).toContain("maxConcurrency !== 1");
    expect(productionRunner).toContain("the canonical owner account is not uniquely eligible");
    expect(productionRunner).toContain("stopOnUnsafeResult: true");
    expect(productionRunner).toContain('guard.mode === "dry_run"');
    expect(productionRunner.indexOf('guard.mode === "dry_run"')).toBeLessThan(productionRunner.indexOf("new MultiAccountExecutor"));
    expect(appSource).not.toContain("run-multi-account-production-cycle");
  });

  it("does not change generated data or outputs", () => {
    expect(gitDiffNames(["data", "outputs"])).toEqual([]);
  });
});
