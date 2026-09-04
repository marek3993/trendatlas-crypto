"use server";

import { revalidatePath } from "next/cache";
import { isHex, type Hex } from "viem";
import { requireUser } from "@/lib/auth/require-user";
import { normalizeHyperliquidAddress } from "@/lib/hyperliquid/address";
import {
  buildApproveAgentAction,
  createEnvironmentAgentSecretProtector,
  encryptGeneratedAgent,
  generateAgentMaterial,
  recoverApproveAgentSigner,
  submitApproveAgentExchangeAction,
  type ApproveAgentAction
} from "@/lib/hyperliquid/agent-authorization";
import { getHyperliquidUserRole } from "@/lib/hyperliquid/info";
import { createAdminClient } from "@/lib/supabase/admin";

const CHALLENGE_TTL_MS = 5 * 60 * 1000;

type AccountRow = { id: string; user_id: string; master_address: string; connection_status: string };
type AuthorizationRow = {
  id: string;
  user_id: string;
  hyperliquid_account_id: string;
  master_address: string;
  agent_address: string;
  agent_name: string;
  authorization_status: string;
};
type ChallengeRow = {
  id: string;
  authorization_id: string;
  user_id: string;
  hyperliquid_account_id: string;
  master_address: string;
  agent_address: string;
  agent_name: string;
  nonce: string | number;
  signature_chain_id: string;
  hyperliquid_chain: string;
  expires_at: string;
  consumed_at: string | null;
};

export type AgentActionState = { message: string; challenge?: { id: string; masterAddress: string; action: { agentAddress: string; agentName: string; nonce: string } } };

function failure(message: string): AgentActionState {
  return { message };
}

async function getOwnedReadOnlyAccount(userId: string): Promise<AccountRow | null> {
  const { data, error } = await createAdminClient()
    .from("hyperliquid_accounts")
    .select("id, user_id, master_address, connection_status")
    .eq("user_id", userId)
    .maybeSingle<AccountRow>();
  if (error || !data || data.connection_status !== "read_only_connected") return null;
  return data;
}

function actionFromChallenge(challenge: ChallengeRow): ApproveAgentAction {
  if (challenge.signature_chain_id !== "0xa4b1" || challenge.hyperliquid_chain !== "Mainnet") {
    throw new Error("invalid approval challenge");
  }
  return buildApproveAgentAction(challenge.agent_address, challenge.agent_name, BigInt(challenge.nonce));
}

/** Creates a fresh, short-lived server-issued action. It never returns key material. */
export async function beginAgentAuthorization(): Promise<AgentActionState> {
  const { user } = await requireUser();
  const account = await getOwnedReadOnlyAccount(user.id);
  if (!account) return failure("Connect a read-only Hyperliquid account first.");

  try {
    const role = await getHyperliquidUserRole(account.master_address);
    if (role.role !== "user") {
      return failure("This Hyperliquid account is not eligible for agent authorization. Use a regular user account.");
    }
  } catch {
    return failure("We could not confirm this Hyperliquid account type. Please try again.");
  }

  const admin = createAdminClient();
  const { data: existing, error: existingError } = await admin
    .from("hyperliquid_agent_authorizations")
    .select("id, authorization_status")
    .eq("user_id", user.id)
    .eq("hyperliquid_account_id", account.id)
    .eq("authorization_status", "authorized")
    .maybeSingle<{ id: string; authorization_status: string }>();
  if (existingError) return failure("We could not check the current authorization. Please try again.");
  if (existing) return failure("Your TrendAtlas agent is already authorized.");

  let material: ReturnType<typeof generateAgentMaterial>;
  let encrypted: ReturnType<typeof encryptGeneratedAgent>;
  try {
    material = generateAgentMaterial();
    encrypted = encryptGeneratedAgent(material, createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64));
  } catch {
    return failure("Agent authorization is not configured. Please contact support.");
  }

  // A previous incomplete attempt is permanently retired; its address is never reused.
  const { error: retireError } = await admin
    .from("hyperliquid_agent_authorizations")
    .update({ authorization_status: "failed" })
    .eq("user_id", user.id)
    .eq("hyperliquid_account_id", account.id)
    .eq("authorization_status", "pending");
  if (retireError) return failure("We could not prepare the authorization. Please try again.");

  const { data: authorization, error: authorizationError } = await admin
    .from("hyperliquid_agent_authorizations")
    .insert({
      user_id: user.id,
      hyperliquid_account_id: account.id,
      master_address: account.master_address,
      agent_address: material.address,
      agent_name: material.name,
      authorization_status: "pending"
    })
    .select("id")
    .single<{ id: string }>();
  if (authorizationError || !authorization) return failure("We could not prepare the authorization. Please try again.");

  const { error: secretError } = await admin.from("hyperliquid_agent_secrets").insert({
    authorization_id: authorization.id,
    encrypted_private_key: encrypted.encryptedPrivateKey,
    encryption_nonce: encrypted.encryptionNonce,
    encryption_key_version: encrypted.encryptionKeyVersion
  });
  if (secretError) {
    await admin.from("hyperliquid_agent_authorizations").update({ authorization_status: "failed" }).eq("id", authorization.id).eq("user_id", user.id);
    return failure("We could not secure the authorization. Please try again.");
  }

  const nonce = BigInt(Date.now());
  const action = buildApproveAgentAction(material.address, material.name, nonce);
  const expiresAt = new Date(Date.now() + CHALLENGE_TTL_MS).toISOString();
  const { data: challenge, error: challengeError } = await admin
    .from("hyperliquid_agent_approval_challenges")
    .insert({
      authorization_id: authorization.id,
      user_id: user.id,
      hyperliquid_account_id: account.id,
      master_address: account.master_address,
      agent_address: action.agentAddress,
      agent_name: action.agentName,
      nonce: Number(action.nonce),
      signature_chain_id: action.signatureChainId,
      hyperliquid_chain: action.hyperliquidChain,
      expires_at: expiresAt
    })
    .select("id")
    .single<{ id: string }>();
  if (challengeError || !challenge) {
    await admin.from("hyperliquid_agent_authorizations").update({ authorization_status: "failed" }).eq("id", authorization.id).eq("user_id", user.id);
    return failure("We could not create the approval request. Please try again.");
  }
  return {
    message: "Connect the wallet that owns this Hyperliquid account to continue.",
    challenge: { id: challenge.id, masterAddress: account.master_address, action: { agentAddress: action.agentAddress, agentName: action.agentName, nonce: action.nonce.toString() } }
  };
}

/** Verifies the server-owned challenge and signer before the only exchange mutation. */
export async function submitAgentAuthorization(challengeId: string, signature: string): Promise<AgentActionState> {
  const { user } = await requireUser();
  if (!isHex(signature, { strict: true }) || signature.length !== 132) return failure("The wallet signature is invalid.");
  const admin = createAdminClient();
  const { data: challenge, error: challengeError } = await admin
    .from("hyperliquid_agent_approval_challenges")
    .select("id, authorization_id, user_id, hyperliquid_account_id, master_address, agent_address, agent_name, nonce, signature_chain_id, hyperliquid_chain, expires_at, consumed_at")
    .eq("id", challengeId)
    .eq("user_id", user.id)
    .maybeSingle<ChallengeRow>();
  if (challengeError || !challenge || challenge.consumed_at || new Date(challenge.expires_at).getTime() <= Date.now()) {
    return failure("This approval request has expired or was already used. Start again to create a new one.");
  }

  const account = await getOwnedReadOnlyAccount(user.id);
  if (!account || account.id !== challenge.hyperliquid_account_id || normalizeHyperliquidAddress(account.master_address) !== challenge.master_address) {
    return failure("This approval request no longer matches your connected account.");
  }
  const { data: authorization } = await admin
    .from("hyperliquid_agent_authorizations")
    .select("id, user_id, hyperliquid_account_id, master_address, agent_address, agent_name, authorization_status")
    .eq("id", challenge.authorization_id)
    .eq("user_id", user.id)
    .maybeSingle<AuthorizationRow>();
  if (!authorization || authorization.authorization_status !== "pending" || authorization.hyperliquid_account_id !== account.id || authorization.master_address !== challenge.master_address || authorization.agent_address !== challenge.agent_address || authorization.agent_name !== challenge.agent_name) {
    return failure("This approval request is no longer valid.");
  }

  let action: ApproveAgentAction;
  try {
    action = actionFromChallenge(challenge);
    const recovered = await recoverApproveAgentSigner(action, signature as Hex);
    if (recovered !== challenge.master_address) return failure("The connected wallet does not control this Hyperliquid account.");
  } catch {
    return failure("The wallet signature could not be verified.");
  }

  const { error: consumeError } = await admin.rpc("consume_hyperliquid_agent_approval_challenge", {
    challenge_id: challenge.id,
    expected_user_id: user.id
  });
  if (consumeError) return failure("This approval request has expired or was already used. Start again to create a new one.");

  try {
    await submitApproveAgentExchangeAction(action, signature as Hex);
  } catch {
    await admin.from("hyperliquid_agent_authorizations").update({ authorization_status: "failed" }).eq("id", authorization.id).eq("user_id", user.id);
    return failure("The agent approval was not confirmed. No trading is active.");
  }

  try {
    const role = await getHyperliquidUserRole(action.agentAddress);
    if (role.role !== "agent" || role.user !== challenge.master_address) throw new Error("agent binding mismatch");
  } catch {
    await admin.from("hyperliquid_agent_authorizations").update({ authorization_status: "failed" }).eq("id", authorization.id).eq("user_id", user.id);
    return failure("The agent could not be verified for this account. No trading is active.");
  }

  const now = new Date().toISOString();
  const { data: confirmed, error: updateError } = await admin
    .from("hyperliquid_agent_authorizations")
    .update({
      authorization_status: "authorized",
      ownership_verified_at: now,
      agent_authorized_at: now,
      auto_trading_requested: true,
      execution_status: "pending_multi_account_executor"
    })
    .eq("id", authorization.id)
    .eq("user_id", user.id)
    .eq("authorization_status", "pending")
    .select("id")
    .maybeSingle<{ id: string }>();
  if (updateError || !confirmed) {
    await admin.from("hyperliquid_agent_authorizations").update({ authorization_status: "failed" }).eq("id", authorization.id).eq("user_id", user.id);
    return failure("Authorization was confirmed but could not be saved. Please contact support.");
  }
  revalidatePath("/dashboard");
  return { message: "TrendAtlas agent authorized." };
}

export async function setAutoTradingRequested(requested: boolean): Promise<AgentActionState> {
  const { user } = await requireUser();
  const account = await getOwnedReadOnlyAccount(user.id);
  if (!account) return failure("Connect a read-only Hyperliquid account first.");
  const { data: updated, error } = await createAdminClient()
    .from("hyperliquid_agent_authorizations")
    .update({
      auto_trading_requested: requested,
      execution_status: requested ? "ready" : "disabled_by_user"
    })
    .eq("user_id", user.id)
    .eq("hyperliquid_account_id", account.id)
    .eq("authorization_status", "authorized")
    .select("id")
    .maybeSingle<{ id: string }>();
  if (error || !updated) return failure("We could not update that preference. Please try again.");
  revalidatePath("/dashboard");
  return { message: requested ? "Auto trading preference is on." : "Auto trading preference is off." };
}
