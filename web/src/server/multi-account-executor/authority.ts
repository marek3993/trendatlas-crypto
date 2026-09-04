import "server-only";

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
