// Sanitized kiosk status rendering fixture, without account or secret data.
function renderTrendStatus(status) {
  const realState = status.real_account_state || "Mimo trhu";
  const realAsset = status.real_account_asset || status.target_asset || "CASH";
  const realExposure = formatExposure(status.real_account_exposure ?? status.target_exposure ?? 0) || "0.00x";
  const modelAsset = status.candidate_asset || status.current_asset || "--";
  const submitState = status.trade_submission_state || "Blokované";
  $("trendPermission").textContent = submitState;
  $("strategyExplanation").textContent = `Reálny účet: ${realState} (${realAsset}, ${realExposure}). Model preferuje: ${modelAsset}. Výkon účtu používa canonical Hyperliquid PnL; vklady a výbery nie sú súčasťou PnL.`;
}
