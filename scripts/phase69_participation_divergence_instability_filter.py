from __future__ import annotations

from phase69_research_only_runner_common import FamilyConfig, main_guard


if __name__ == "__main__":
    main_guard(
        FamilyConfig(
            family_id="participation_divergence_instability_filter",
            state_label="participation_divergence_instability_state",
            evidence_gate_reason="instability_veto_events_scored_from_phase68i_context_against_phase67j_forward_returns",
            family_note="Participation-divergence instability is scored as a veto on blocked or incoherent pre-trigger context, with phase67j retained as the only primary compare baseline.",
        ),
        "phase69_participation_divergence_instability_filter.py",
    )
