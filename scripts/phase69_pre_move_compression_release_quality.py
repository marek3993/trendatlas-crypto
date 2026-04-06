from __future__ import annotations

from phase69_research_only_runner_common import FamilyConfig, main_guard


if __name__ == "__main__":
    main_guard(
        FamilyConfig(
            family_id="pre_move_compression_release_quality",
            state_label="pre_move_release_quality_state",
            evidence_gate_reason="pre_move_quality_events_scored_from_phase68i_context_against_phase67j_forward_returns",
            family_note="Compression-release quality is scored from tight pre-trigger return structure plus clean release alignment, with phase67j as the only primary compare baseline.",
        ),
        "phase69_pre_move_compression_release_quality.py",
    )
