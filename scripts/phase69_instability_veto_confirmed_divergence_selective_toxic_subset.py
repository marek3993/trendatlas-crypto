from __future__ import annotations

from phase69_research_only_runner_common import FamilyConfig, main_guard


if __name__ == "__main__":
    main_guard(
        FamilyConfig(
            family_id="instability_veto_confirmed_divergence_selective_toxic_subset",
            state_label="instability_veto_confirmed_divergence_selective_toxic_subset_state",
            evidence_gate_reason="veto_requires_confirmed_pre_move_divergence_plus_selective_toxic_subset_before_phase67j_forward_scoring",
            family_note="Fragility vetoes are applied only when confirmed pre-expansion divergence falls into a deterministic selective toxic subset, while phase67j remains the only primary compare baseline and phase68i stays overlay-context only.",
        ),
        "phase69_instability_veto_confirmed_divergence_selective_toxic_subset.py",
    )
