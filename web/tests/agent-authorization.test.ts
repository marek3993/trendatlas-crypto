import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  buildApproveAgentAction,
  createEnvironmentAgentSecretProtector,
  encryptGeneratedAgent,
  generateAgentMaterial,
  recoverApproveAgentSigner,
  submitApproveAgentExchangeAction
} from "@/lib/hyperliquid/agent-authorization";

const { recoverTypedDataAddress, parseSignature } = vi.hoisted(() => ({
  recoverTypedDataAddress: vi.fn(),
  parseSignature: vi.fn()
}));
vi.mock("viem", () => ({
  isAddress: () => true,
  parseSignature,
  recoverTypedDataAddress
}));
vi.mock("viem/accounts", () => ({
  generatePrivateKey: () => "test-generated-key",
  privateKeyToAccount: () => ({ address: "0x1111111111111111111111111111111111111111" })
}));

const webRoot = process.cwd();
const repoRoot = path.resolve(webRoot, "..");
const source = (file: string) => fs.readFileSync(path.join(webRoot, file), "utf8");
const migration = source("supabase/migrations/202609040004_create_hyperliquid_agent_authorizations.sql");
const authorization = source("src/lib/hyperliquid/agent-authorization.ts");
const typedData = source("src/lib/hyperliquid/approve-agent-typed-data.ts");
const actions = source("src/app/dashboard/agent-actions.ts");
const panel = source("src/components/agent-authorization-panel.tsx");
const info = source("src/lib/hyperliquid/info.ts");

describe("Stage 4 agent authorization boundary", () => {
  it("mocks server-side generation and proves encryption round-trips without browser exposure", () => {
    const generated = generateAgentMaterial();
    const protector = createEnvironmentAgentSecretProtector(Buffer.alloc(32).toString("base64"));
    const encrypted = encryptGeneratedAgent(generated, protector);
    expect(generated.address).toBe("0x1111111111111111111111111111111111111111");
    expect(encrypted.encryptedPrivateKey).not.toContain(generated.privateKey);
    expect(protector.decrypt(encrypted)).toBe(generated.privateKey);
  });

  it("mocks EIP-712 recovery and uses it only for the exact challenge action", async () => {
    const master = "0x2222222222222222222222222222222222222222";
    recoverTypedDataAddress.mockResolvedValueOnce(master);
    const action = buildApproveAgentAction("0x3333333333333333333333333333333333333333", "TA-a1b2c3d4", 123n);
    const signer = await recoverApproveAgentSigner(action, `0x${"44".repeat(65)}` as `0x${string}`);
    expect(signer).toBe(master);
  });

  it("mocks the exchange transport and proves a forbidden order never reaches it", async () => {
    const fetcher = vi.fn();
    await expect(submitApproveAgentExchangeAction({ type: "order" } as never, `0x${"44".repeat(65)}` as `0x${string}`, fetcher)).rejects.toThrow("not allowed");
    expect(fetcher).not.toHaveBeenCalled();
    expect(parseSignature).not.toHaveBeenCalled();
  });

  it("allows only regular Hyperliquid user accounts to start onboarding", () => {
    expect(actions).toContain('if (role.role !== "user")');
  });

  it("recognizes agent, vault, subaccount, and missing roles as non-eligible", () => {
    expect(info).toContain('"missing" | "user" | "agent" | "vault" | "subAccount"');
    expect(actions).toContain("not eligible for agent authorization");
  });

  it("generates the agent key only in a server-only module", () => {
    expect(authorization).toContain('import "server-only"');
    expect(authorization).toContain("generatePrivateKey()");
    expect(actions).toContain('"use server"');
    expect(panel).not.toContain("generateAgentMaterial");
  });

  it("never returns agent private material to the browser", () => {
    expect(actions).not.toMatch(/privateKey\s*:/);
    expect(actions).not.toContain("material.privateKey");
    expect(panel).not.toMatch(/privateKey|seed phrase input|secret input/i);
  });

  it("encrypts generated private material with AES-256-GCM before secret persistence", () => {
    expect(authorization).toContain('createCipheriv("aes-256-gcm"');
    expect(authorization).toContain("cipher.getAuthTag()");
    expect(actions.indexOf("encryptGeneratedAgent(material")).toBeLessThan(actions.indexOf('from("hyperliquid_agent_secrets").insert'));
  });

  it("rejects malformed KEKs and requires exactly 32 decoded bytes", () => {
    expect(authorization).toContain("/^[A-Za-z0-9+/]{43}=$/");
    expect(authorization).toContain("key.length !== 32");
  });

  it("keeps secret storage completely unavailable to browser roles", () => {
    expect(migration).toContain("revoke all on table public.hyperliquid_agent_secrets from public, anon, authenticated");
    expect(migration).not.toMatch(/grant\s+(select|insert|update|delete)[^;]*hyperliquid_agent_secrets[^;]*authenticated/i);
    expect(migration).not.toMatch(/create policy[^;]*hyperliquid_agent_secrets/i);
  });

  it("isolates authorization metadata with RLS and authenticated ownership", () => {
    expect(migration).toContain("force row level security");
    expect(migration).toContain("hyperliquid_agent_authorizations_select_own");
    expect(migration).toContain("(select auth.uid()) = user_id");
  });

  it("binds every challenge to user, account, master, agent, and nonce", () => {
    ["user_id", "hyperliquid_account_id", "master_address", "agent_address", "agent_name", "nonce", "signature_chain_id", "hyperliquid_chain"].forEach((field) => {
      expect(migration).toContain(field);
    });
    expect(actions).toContain('.eq("user_id", user.id)');
  });

  it("rejects expired challenges before an exchange call", () => {
    expect(actions).toContain("new Date(challenge.expires_at).getTime() <= Date.now()");
  });

  it("rejects consumed challenges and atomically consumes a valid challenge once", () => {
    expect(actions).toContain("challenge.consumed_at");
    expect(migration).toContain("consumed_at is null");
    expect(migration).toContain("set consumed_at = timezone('utc', now())");
  });

  it("stops before signing when the browser wallet and master account differ", () => {
    const mismatch = panel.indexOf("normalizeHyperliquidAddress(connected) !== challenge.masterAddress");
    const signing = panel.indexOf("wallet.signTypedData");
    expect(mismatch).toBeGreaterThanOrEqual(0);
    expect(signing).toBeGreaterThan(mismatch);
    expect(panel).toContain("No signature was requested.");
  });

  it("recovers the EIP-712 signer and requires the stored master address", () => {
    expect(authorization).toContain("recoverTypedDataAddress");
    expect(actions).toContain("recovered !== challenge.master_address");
  });

  it("uses the official Hyperliquid approveAgent EIP-712 shape", () => {
    expect(typedData).toContain('"HyperliquidTransaction:ApproveAgent"');
    expect(typedData).toContain('name: "HyperliquidSignTransaction"');
    expect(typedData).toContain("chainId: HYPERLIQUID_MAINNET_CHAIN_ID");
    expect(typedData).toContain('HYPERLIQUID_SIGNATURE_CHAIN_ID = "0xa4b1"');
  });

  it("reconstructs the signed action only from server challenge data", () => {
    expect(actions).toContain("actionFromChallenge(challenge)");
    expect(actions).not.toContain("action: unknown");
  });

  it("allows exactly approveAgent at the exchange boundary", () => {
    expect(authorization).toContain('ALLOWED_EXCHANGE_ACTION_TYPES = ["approveAgent"]');
    expect(authorization).toContain("assertAllowedExchangeAction(action)");
  });

  it("rejects an order before network access", () => {
    const guard = authorization.indexOf("assertAllowedExchangeAction(action)");
    const request = authorization.indexOf("response = await fetcher");
    expect(guard).toBeGreaterThanOrEqual(0);
    expect(request).toBeGreaterThan(guard);
    expect(authorization).not.toContain('"order"');
  });

  it("has no cancel capability", () => {
    expect(authorization).not.toContain('"cancel"');
    expect(actions).not.toMatch(/cancel(Order|\s*\()/i);
  });

  it("has no transfer or withdrawal capability", () => {
    expect(authorization).not.toMatch(/transfer\s*\(|withdraw\s*\(|usdSend|spotSend/i);
    expect(actions).not.toMatch(/transfer\s*\(|withdraw\s*\(|usdSend|spotSend/i);
  });

  it("does not accept an exchange success response without independent userRole verification", () => {
    const submit = actions.indexOf("await submitApproveAgentExchangeAction");
    const verify = actions.indexOf("await getHyperliquidUserRole(action.agentAddress)");
    const update = actions.indexOf('authorization_status: "authorized"');
    expect(verify).toBeGreaterThan(submit);
    expect(update).toBeGreaterThan(verify);
  });

  it("requires an agent role bound to the exact stored master", () => {
    expect(actions).toContain('role.role !== "agent" || role.user !== challenge.master_address');
  });

  it("defaults the saved auto-trading preference to on only after verified authorization", () => {
    expect(migration).toContain("auto_trading_requested boolean not null default true");
    expect(actions).toContain("auto_trading_requested: true");
  });

  it("marks a verified authorization ready without exposing a Vercel execution path", () => {
    expect(actions).toContain('execution_status: "ready"');
    expect(actions).not.toContain("run-multi-account-production-cycle");
    expect(panel).toContain("Live executor: not enabled yet");
  });

  it("changes the local preference without invoking Hyperliquid", () => {
    const preference = actions.slice(actions.indexOf("export async function setAutoTradingRequested"));
    expect(preference).not.toContain("getHyperliquidUserRole");
    expect(preference).not.toContain("submitApproveAgentExchangeAction");
  });

  it("does not copy a production signer or address into web source", () => {
    const production = fs.readFileSync(path.join(repoRoot, "scripts/execution/run_trendatlas_production.py"), "utf8");
    const protectedAddresses = production.match(/0x[a-fA-F0-9]{40}/g) ?? [];
    const webSource = [authorization, actions, panel].join("\n");
    protectedAddresses.forEach((address) => expect(webSource).not.toContain(address));
    expect(webSource).not.toContain("TrendAtlasProd");
  });

  it("keeps the approved production executor unreachable from authorization actions", () => {
    const production = fs.readFileSync(path.join(repoRoot, "scripts/execution/run_trendatlas_production.py"), "utf8");
    expect(production).toContain("run_multi_account_backend");
    expect(actions).not.toContain("run_multi_account_backend");
    expect(actions).not.toContain("run-multi-account-production-cycle");
  });

  it("does not modify generated data or outputs", () => {
    const changed = execFileSync("git", ["diff", "--name-only", "--", "data", "outputs"], { cwd: repoRoot, encoding: "utf8" });
    expect(changed.trim()).toBe("");
  });
});
