import "server-only";

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { SUPPORTED_TARGETS, type AuthorizedTarget, type TargetAsset } from "./types";

export class AuthorityError extends Error {}
type RecordValue = Record<string, unknown>;
const asRecord = (value: unknown): RecordValue => value !== null && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const asString = (value: unknown): string | null => typeof value === "string" && value.trim() ? value.trim() : null;
const asNumber = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;

/** Accepts only a successful Pi authority snapshot with matching intent and gate provenance. */
export function parseAuthorizedTarget(snapshotValue: unknown, attemptValue: unknown): AuthorizedTarget {
  const snapshot = asRecord(snapshotValue);
  const attempt = asRecord(attemptValue);
  const runtime = asRecord(snapshot.app_runtime_snapshot);
  const intent = asRecord(runtime.execution_intent_summary);
  const gate = asRecord(runtime.gate_summary);
  const context = asRecord(gate.production_signal_context);
  const closedDay = asString(snapshot.target_closed_day_utc);
  const strategyVersion = asString(context.strategy_version);
  const signalId = asString(intent.signal_id);
  const asset = asString(intent.target_asset);
  const exposure = asNumber(context.target_exposure) ?? (asset === "CASH" ? 0 : asNumber(intent.target_exposure));
  if (snapshot.artifact_type !== "authority_latest_successful_snapshot" || attempt.artifact_type !== "authority_latest_attempt_status" || snapshot.schema_version !== 1 || attempt.schema_version !== 1) throw new AuthorityError("authority schema is invalid");
  if (snapshot.latest_authoritative_attempt_status !== "success" || snapshot.attempt_stage_status !== "success" || attempt.latest_authoritative_attempt_status !== "success" || attempt.attempt_stage_status !== "success") throw new AuthorityError("authority publication was unsuccessful");
  if (snapshot.run_id !== attempt.run_id || closedDay !== asString(attempt.target_closed_day_utc) || closedDay !== asString(context.closed_day) || closedDay !== asString(snapshot.strategy_artifact_closed_day_utc)) throw new AuthorityError("authority provenance does not match");
  if (snapshot.currentness_status !== "current" || intent.stale_signal !== false || context.validation_status !== "passed") throw new AuthorityError("authority is stale or invalid");
  if (!closedDay || !strategyVersion || !signalId || !asset || exposure === null || exposure < 0 || !SUPPORTED_TARGETS.includes(asset as TargetAsset)) throw new AuthorityError("authority target is unsupported or ambiguous");
  if (asset === "CASH" && exposure !== 0) throw new AuthorityError("cash authority exposure is invalid");
  if (asset !== "CASH" && (exposure <= 0 || intent.target_asset !== context.target_asset || intent.signal_id !== context.signal_id)) throw new AuthorityError("authority target provenance does not match");
  const gateState = gate.status === "no_action" ? "no_action" : gate.approval_gate_status === "approved_and_applied" && gate.would_place_real_order === true ? "approved" : null;
  if (!gateState) throw new AuthorityError("authority gate does not permit the target");
  return { strategyVersion, closedDay, signalId, asset: asset as TargetAsset, exposure, stale: false, executionGate: gateState };
}

export async function loadAuthorizedTarget(repositoryRoot: string): Promise<AuthorizedTarget> {
  const base = path.join(repositoryRoot, "outputs", "execution", "authority");
  const [snapshot, attempt] = await Promise.all([
    readFile(path.join(base, "latest_successful_snapshot.json"), "utf8"),
    readFile(path.join(base, "latest_attempt_status.json"), "utf8")
  ]);
  return parseAuthorizedTarget(JSON.parse(snapshot), JSON.parse(attempt));
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

/**
 * Loads the target created inside the currently locked canonical production run.
 * This path is only for the orchestrator-owned multi-account execution stage,
 * before that same run is allowed to publish its terminal authority snapshot.
 */
export async function loadCanonicalRunTarget(
  repositoryRoot: string,
  expectedRunId: string,
  expectedSignalId: string
): Promise<AuthorizedTarget> {
  if (!expectedRunId.trim() || !expectedSignalId.trim()) throw new AuthorityError("canonical run binding is missing");
  const productionPath = path.join(repositoryRoot, "outputs", "production", "current_strategy_snapshot.json");
  const intentPath = path.join(repositoryRoot, "outputs", "execution", "intents", "latest_execution_intent.json");
  const gatePath = path.join(repositoryRoot, "outputs", "execution", "live_gate", "latest_real_order_gate_decision.json");
  const accountPath = path.join(repositoryRoot, "outputs", "execution", "read_only", "hyperliquid_account_snapshot.json");
  const [productionText, intentText, gateText, accountText] = await Promise.all([
    readFile(productionPath, "utf8"),
    readFile(intentPath, "utf8"),
    readFile(gatePath, "utf8"),
    readFile(accountPath, "utf8")
  ]);
  const production = asRecord(JSON.parse(productionText));
  const productionIntent = asRecord(production.execution_intent);
  const intent = asRecord(JSON.parse(intentText));
  const gate = asRecord(JSON.parse(gateText));
  const context = asRecord(gate.production_signal_context);
  const fingerprints = asRecord(gate.source_fingerprints);
  const intentFingerprints = asRecord(intent.source_fingerprints);
  const strategyVersion = asString(production.strategy_version);
  const closedDay = asString(production.closed_day);
  const signalId = asString(productionIntent.signal_id);
  const asset = asString(productionIntent.target_asset);
  const exposure = asNumber(productionIntent.target_exposure);

  if (process.env.MRV1_CURRENT_AUTHORITY_RUN_ID !== expectedRunId) throw new AuthorityError("canonical run id does not match the orchestrator");
  if (process.env.MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY !== closedDay) throw new AuthorityError("canonical closed day does not match the orchestrator");
  if (production.artifact_type !== "current_strategy_snapshot" || production.schema_version !== 4) throw new AuthorityError("Production Core schema is invalid");
  if (!strategyVersion || !closedDay || !signalId || signalId !== expectedSignalId || !asset || exposure === null) throw new AuthorityError("canonical target is incomplete");
  if (!SUPPORTED_TARGETS.includes(asset as TargetAsset) || productionIntent.stale_signal !== false || asRecord(production.validation).status !== "passed") throw new AuthorityError("canonical target is stale or unsupported");
  if (intent.signal_id !== signalId || intent.target_asset !== asset || asNumber(intent.target_size_pct) !== exposure || intent.strategy_model !== strategyVersion || intent.as_of_source !== closedDay || intent.stale_signal !== false) throw new AuthorityError("canonical intent does not match Production Core");
  if (context.signal_id !== signalId || context.target_asset !== asset || asNumber(context.target_exposure) !== exposure || context.strategy_version !== strategyVersion || context.closed_day !== closedDay || context.validation_status !== "passed") throw new AuthorityError("canonical gate does not match Production Core");
  if (fingerprints.production_snapshot_sha256 !== sha256(productionText) || intentFingerprints.production_snapshot_sha256 !== sha256(productionText) || fingerprints.intent_sha256 !== sha256(intentText) || fingerprints.account_snapshot_sha256 !== sha256(accountText)) throw new AuthorityError("canonical source fingerprints do not match");
  const gatePermitsTarget = gate.status === "no_action" || (gate.approval_gate_status === "approved_and_applied" && gate.real_orders_enabled === true && gate.would_place_real_order === true);
  if (!gatePermitsTarget) throw new AuthorityError("canonical gate does not permit execution");
  if ((asset === "CASH" && exposure !== 0) || (asset !== "CASH" && exposure <= 0)) throw new AuthorityError("canonical target exposure is invalid");
  return { strategyVersion, closedDay, signalId, asset: asset as TargetAsset, exposure, stale: false, executionGate: gate.status === "no_action" ? "no_action" : "approved" };
}
