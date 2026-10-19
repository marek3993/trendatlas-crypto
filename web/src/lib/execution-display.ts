/** Public descriptions only; never infer wallet holdings from execution history. */
export function executionOutcomeLabel(status: string | null | undefined): string {
  switch (status) {
    case "FILLED_AND_ALIGNED": return "Aligned with strategy";
    case "NO_ACTION": return "Already aligned";
    case "EXITED_ENTRY_FAILED_STAYING_CASH": return "Positions closed; staying in cash";
    case "ENTRY_FAILED_STAYING_CASH": return "Entry unavailable; staying in cash";
    case "UNKNOWN_SUBMISSION_STATE": return "Awaiting exchange confirmation";
    case "PARTIAL": return "Partially completed";
    case "BLOCKED": return "Unable to proceed at last check";
    case "FAILED": return "Last attempt failed";
    case "DRY_RUN": return "Preview only";
    case "DISABLED": return "Automatic trading is off";
    default: return "No completed attempt available";
  }
}

export function automaticTradingLabel(enabled: boolean, consent: boolean, status: string): string {
  if (!consent) return "Off";
  if (!enabled) return "Service unavailable";
  if (["blocked", "error"].includes(status)) return "Will recheck on the next scheduled run";
  if (["ready", "aligned"].includes(status)) return "Ready";
  if (status === "executing") return "In progress";
  return "Authorization needs attention";
}
