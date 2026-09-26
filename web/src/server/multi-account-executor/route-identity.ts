/** Bound to the Python Production Core contract; never infer a target from a candidate. */
export const routeFields = ["route_type", "base_economic_asset", "candidate_asset", "candidate_trigger_active",
  "resolved_execution_asset", "resolution_reason", "signal_available_at"] as const;

export function validateResolvedRoute(production: Record<string, unknown>, intent: Record<string, unknown>): void {
  const embedded = production.execution_intent as Record<string, unknown> | undefined;
  if (!embedded || routeFields.some((key) => production[key] === undefined || embedded[key] !== production[key] || intent[key] !== production[key])) throw new Error("Canonical route lineage is missing or inconsistent.");
  const route = production.route_type;
  const active = production.candidate_trigger_active;
  if (typeof active !== "boolean") throw new Error("Candidate trigger must be explicit.");
  const expected = route === "CASH" ? "CASH" : route === "BTC" ? "BTC" : route === "BASE" && !active ? production.base_economic_asset : route === "CANDIDATE" && active ? production.candidate_asset : null;
  const reasons = { CASH: "cash_route", BTC: "btc_route", BASE: "same_interval_base_holding", CANDIDATE: "active_candidate_trigger" };
  if (typeof route !== "string" || !Object.hasOwn(reasons, route) || production.resolution_reason !== reasons[route as keyof typeof reasons]) throw new Error("Canonical route resolution reason is invalid.");
  if (typeof expected !== "string" || !/^[A-Z][A-Z0-9]*$/.test(expected) || ["BASE", "BASELINE", "CANDIDATE", "ALT"].includes(expected)) throw new Error("Concrete economic target is required.");
  if ([production.resolved_execution_asset, production.current_asset, production.actual_held_asset, embedded.target_asset, intent.target_asset].some((value) => value !== expected)) throw new Error("Canonical route target identity differs.");
  const exposure = embedded.target_exposure;
  if (typeof exposure !== "number" || !Number.isFinite(exposure) || (expected === "CASH" ? exposure !== 0 : exposure <= 0)) throw new Error("Canonical route exposure is invalid.");
  const available = Date.parse(String(production.signal_available_at));
  const close = Date.parse(`${production.closed_day}T00:00:00Z`) + 86_400_000;
  if (!Number.isFinite(available) || !Number.isFinite(close) || available <= close || available > Date.now()) throw new Error("Canonical signal availability is invalid.");
}
