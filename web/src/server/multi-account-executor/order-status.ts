import type { KnownOrder } from "./engine";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function orderIdFrom(value: unknown): string | undefined {
  const record = asRecord(value);
  const order = asRecord(record?.order);
  const innerOrder = asRecord(order?.order);
  const candidate = innerOrder?.oid ?? order?.oid ?? record?.oid;
  return typeof candidate === "string" || typeof candidate === "number"
    ? String(candidate)
    : undefined;
}

export function normalizeHyperliquidOrderStatus(value: unknown): KnownOrder {
  if (Array.isArray(value)) {
    return value.length > 0 ? normalizeHyperliquidOrderStatus(value[0]) : { state: "unknown" };
  }
  const record = asRecord(value);
  if (!record) return { state: "unknown" };
  if (record.data !== undefined) return normalizeHyperliquidOrderStatus(record.data);
  if (Array.isArray(record.statuses) && record.statuses.length > 0) {
    return normalizeHyperliquidOrderStatus(record.statuses[0]);
  }

  const order = asRecord(record.order);
  const rawStatus = record.status === "order" ? order?.status : record.status ?? order?.status;
  if (typeof rawStatus !== "string") return { state: "unknown", orderId: orderIdFrom(record) };
  const status = rawStatus.replace(/[^a-z0-9]/gi, "").toLowerCase();
  const orderId = orderIdFrom(record);
  if (status === "unknownoid" || status === "notfound" || status === "missing") return null;
  if (status === "filled") return { state: "filled", orderId };
  if (status === "open") return { state: "open", orderId };
  if (status.includes("cancel")) return { state: "cancelled", orderId };
  if (status.includes("reject") || status === "error") {
    return { state: "rejected", orderId };
  }
  return { state: "unknown", orderId };
}
