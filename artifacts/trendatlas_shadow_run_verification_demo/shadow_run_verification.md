# TrendAtlas Local Shadow-Run Verification

- Verified at: `2026-04-25T11:45:50Z`
- Family: `cost_aware_hysteretic_pilot_to_full`
- Final status: `working`
- Retrieval packet: `C:\Users\benda\Desktop\market_regime_v1\outputs\research_os\dev_only\imlayer_retrieval\20260424T220103Z\cost_aware_hysteretic_pilot_to_full.latest.retrieval_packet.json`
- Retrieval memory id: `trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full`
- Retrieval semantic sha256: `591a4e4eabc4c5f9dc53f22636cf99826e2b44201ec08063c8f7b4dc9e4e80e7`

## Planner

- Passive comparison bucket: `with_retrieval_packet`
- Controlled enabled: `True`
- Candidate status: `completed`
- Fail-closed preserved: `True`
- Authoritative mutation target: `state_machine.pilot_entry.recap_confirm_gate`
- Changed note fields: `mechanism_hypothesis, selection_rationale`

## Critic

- Passive comparison bucket: `with_retrieval_packet`
- Controlled enabled: `True`
- Candidate status: `completed`
- Fail-closed preserved: `True`
- Authoritative verdict: `pause`
- Authoritative next action: `pause_family`
- Changed note fields: `policy_alignment_note, recommended_reason`

## Governor

- Invoked by verifier: `False`
- Unchanged by verifier: `True`
- Latest existing governor artifact: `C:\Users\benda\Desktop\market_regime_v1\outputs\research_os\dev_only\mvp\artifacts\governor_outputs\third_openai_backed_cycle_cost_aware_hysteretic_pilot_to_full_governor_family_governor_state.json`
