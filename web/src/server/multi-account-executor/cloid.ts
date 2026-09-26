import "server-only";

import { createHash } from "node:crypto";

export function deterministicCloid(input: { userId: string; accountId: string; signalId: string; closedDay: string; target: string; action: string; leg: number; attempt: number; asset?: string; side?: string; orderId?: string }): string {
  // Asset/side identities survive a restart after any preceding position closes.
  const identity = JSON.stringify(input.asset ? { ...input, leg: 0 } : input);
  return `0x${createHash("sha256").update(identity).digest("hex").slice(0, 32)}`;
}
