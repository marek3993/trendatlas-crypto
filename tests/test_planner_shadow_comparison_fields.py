import unittest
from types import SimpleNamespace

from scripts.research_os_local_shadow_run_verification import (
    VerificationFailure,
    assert_planner_invariants,
)
from services.pi import planner_service

class PlannerShadowComparisonFieldsTests(unittest.TestCase):
    def test_planner_note_fields_exclude_proposal_content_fields(self) -> None:
        note_fields = planner_service._planner_note_fields_from_response(
            {
                "mechanism_hypothesis": "reasoning text",
                "selection_rationale": "selection text",
                "mutation_target": {
                    "target_id": "rule.a",
                    "target_type": "single_rule",
                    "source_artifact_id": "artifact-1",
                    "exact_change": "change text",
                },
                "stop_condition": "stop text",
            }
        )

        self.assertEqual(
            note_fields,
            {
                "mechanism_hypothesis": "reasoning text",
                "selection_rationale": "selection text",
            },
        )

    def test_shadow_planner_comparison_freezes_proposal_content_fields(self) -> None:
        response = SimpleNamespace(
            response_id="resp_123",
            status="completed",
            model="gpt-test",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            parsed={
                "mechanism_hypothesis": "retrieval-adjusted reasoning",
                "selection_rationale": "retrieval-adjusted rationale",
                "mutation_target": {
                    "target_id": "different.target",
                    "target_type": "different_type",
                    "source_artifact_id": "different-artifact",
                    "exact_change": "different change",
                },
                "stop_condition": "different stop",
            },
        )

        frozen_fields = {
            "exact_change": "authoritative change",
            "source_artifact_id": "authoritative-artifact",
            "stop_condition": "authoritative stop",
            "target_id": "authoritative.target",
            "target_type": "authoritative_type",
        }

        def fake_invoke(*, user_payload, openai_config):  # noqa: ARG001
            return response

        original = planner_service._invoke_planner_openai_response
        planner_service._invoke_planner_openai_response = fake_invoke
        try:
            shadow_result = planner_service._run_shadow_planner_comparison(
                user_payload={"prompt": "shadow"},
                openai_config={"enabled": True},
                frozen_proposal_content_fields=frozen_fields,
            )
        finally:
            planner_service._invoke_planner_openai_response = original

        self.assertEqual(
            shadow_result["note_fields"],
            {
                "mechanism_hypothesis": "retrieval-adjusted reasoning",
                "selection_rationale": "retrieval-adjusted rationale",
            },
        )
        self.assertEqual(shadow_result["proposal_content_fields"], frozen_fields)
        self.assertEqual(
            shadow_result["raw_proposal_content_fields"],
            {
                "exact_change": "different change",
                "source_artifact_id": "different-artifact",
                "stop_condition": "different stop",
                "target_id": "different.target",
                "target_type": "different_type",
            },
        )

    def test_assert_planner_invariants_rejects_unpreserved_proposal_content(self) -> None:
        output = SimpleNamespace(
            openai_hook={
                "failure_closed": False,
                "controlled_retrieval_comparison": {
                    "explicitly_enabled": True,
                    "decision_behavior_changed": False,
                    "fail_closed_preserved": True,
                    "observations": {
                        "candidate": {
                            "status": "completed",
                            "error": "",
                        },
                        "diff": {
                            "proposal_content_fields_preserved": False,
                            "proposal_content_fields_changed": ["exact_change"],
                        },
                    },
                },
                "passive_retrieval_comparison": {
                    "comparison_bucket": "with_retrieval_packet",
                },
            }
        )

        with self.assertRaisesRegex(
            VerificationFailure,
            "planner shadow candidate changed proposal content fields",
        ):
            assert_planner_invariants(output)


if __name__ == "__main__":
    unittest.main()
