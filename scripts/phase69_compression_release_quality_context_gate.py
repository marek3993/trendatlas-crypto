from __future__ import annotations

from phase69_research_only_runner_common import FamilyConfig, main_guard


if __name__ == "__main__":
    main_guard(
        FamilyConfig(
            family_id="compression_release_quality_context_gate",
            state_label="compression_release_quality_context_gate_state",
            evidence_gate_reason="compression_release_events_require_clean_pre_move_structure_plus_confirming_context_before_phase67j_forward_scoring",
            family_note="Compression-release approvals require both clean release structure and explicit pre-expansion context confirmation, while phase67j remains the only primary compare baseline and phase68i stays overlay-context only.",
        ),
        "phase69_compression_release_quality_context_gate.py",
    )
