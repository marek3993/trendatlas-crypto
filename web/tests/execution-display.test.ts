import { describe, expect, it } from "vitest";
import { automaticTradingLabel, executionOutcomeLabel } from "@/lib/execution-display";

describe("public execution status", () => {
  it("shows cash outcomes without claiming that a strategy position is held", () => {
    expect(executionOutcomeLabel("EXITED_ENTRY_FAILED_STAYING_CASH")).toBe("Positions closed; staying in cash");
    expect(executionOutcomeLabel("ENTRY_FAILED_STAYING_CASH")).toBe("Entry unavailable; staying in cash");
    expect(executionOutcomeLabel("UNKNOWN_SUBMISSION_STATE")).toBe("Awaiting exchange confirmation");
    expect(executionOutcomeLabel(null)).toBe("No completed attempt available");
  });
  it("keeps temporary failures eligible and distinguishes user consent and service availability", () => {
    for (const status of ["blocked", "error"]) expect(automaticTradingLabel(true, true, status)).toContain("next scheduled run");
    expect(automaticTradingLabel(true, false, "ready")).toBe("Off");
    expect(automaticTradingLabel(false, true, "ready")).toBe("Service unavailable");
  });
});
