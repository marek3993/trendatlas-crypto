import "server-only";

import { createHash } from "node:crypto";

export function deterministicCloid(input: { userId: string; accountId: string; signalId: string; closedDay: string; target: string; action: string; leg: number; attempt: number }): string {
  const identity = JSON.stringify(input);
  return `0x${createHash("sha256").update(identity).digest("hex").slice(0, 32)}`;
}
