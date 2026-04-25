import unittest
from pathlib import Path
import shutil
from unittest import mock

from scripts import research_os_shadow_batch_eval as batch_eval
from scripts import research_os_local_shadow_run_verification as verifier


class ResearchOsShadowBatchEvalV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path("tests_runtime_shadow_batch_eval_v3")
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_summarize_component_tracks_output_delta_and_identical_decisions(self) -> None:
        component = batch_eval.summarize_component(
            "planner",
            {
                "observations": {
                    "diff": {
                        "changed_fields": ["mechanism_hypothesis", "selection_rationale"],
                        "proposal_content_fields_changed": [],
                        "proposal_content_fields_preserved": True,
                    },
                    "authoritative": {
                        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    },
                    "candidate": {
                        "status": "completed",
                        "error": "",
                        "response_id": "resp_candidate",
                        "response_status": "completed",
                        "response_model": "gpt-test",
                        "usage": {"input_tokens": 140, "output_tokens": 32, "total_tokens": 172},
                    },
                },
                "authoritative_prompt_metrics": {
                    "estimated_input_tokens_char_div4": 200,
                    "json_char_count": 800,
                    "utf8_byte_count": 800,
                    "payload_sha256": "aaa",
                },
                "candidate_prompt_metrics": {
                    "estimated_input_tokens_char_div4": 260,
                    "json_char_count": 1040,
                    "utf8_byte_count": 1040,
                    "payload_sha256": "bbb",
                },
                "candidate_prompt_mode": "compact",
                "retrieval_prompt_observability": {
                    "selected_mode": "compact",
                    "full_retrieval_mode": {
                        "prompt_metrics": {
                            "estimated_input_tokens_char_div4": 360,
                            "json_char_count": 1440,
                            "utf8_byte_count": 1440,
                            "payload_sha256": "full-bbb",
                        }
                    },
                    "compact_retrieval_mode": {
                        "prompt_metrics": {
                            "estimated_input_tokens_char_div4": 260,
                            "json_char_count": 1040,
                            "utf8_byte_count": 1040,
                            "payload_sha256": "bbb",
                        }
                    },
                    "token_delta_impact": {
                        "full_vs_authoritative": {
                            "estimated_input_tokens_char_div4_delta": 160,
                            "json_char_count_delta": 640,
                            "utf8_byte_count_delta": 640,
                        },
                        "compact_vs_authoritative": {
                            "estimated_input_tokens_char_div4_delta": 60,
                            "json_char_count_delta": 240,
                            "utf8_byte_count_delta": 240,
                        },
                        "compact_vs_full": {
                            "estimated_input_tokens_char_div4_delta": -100,
                            "json_char_count_delta": -400,
                            "utf8_byte_count_delta": -400,
                        },
                    },
                },
                "decision_behavior_changed": False,
                "fail_closed_preserved": True,
            },
            {
                "network_call": "completed",
                "response_id": "resp_authoritative",
                "response_status": "completed",
                "response_model": "gpt-test",
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            },
            {
                "comparison_bucket": "with_retrieval_packet",
                "retrieval_packet_present": True,
                "retrieval_packet_status": "loaded",
                "latest_memory_id": "memory-1",
                "semantic_sha256": "sha-1",
                "load_error": "",
            },
            reasoning_fields=batch_eval.PLANNER_REASONING_FIELDS,
            decision_fields=batch_eval.PLANNER_DECISION_FIELDS,
        )

        self.assertTrue(component["reasoning_changed"])
        self.assertTrue(component["decision_stayed_identical"])
        self.assertTrue(component["reasoning_changed_decision_identical"])
        self.assertEqual(component["response_output_tokens_delta"], 12)
        self.assertEqual(component["response_total_tokens_delta"], 52)

    def test_build_summary_records_v3_measurements(self) -> None:
        case = {
            "family_id": "family.alpha",
            "cycle_label": "cycle_one",
            "retrieval_packet_path": "C:\\retrieval.json",
            "planner_input_path": "C:\\planner_input.json",
            "heavy_validation_summary_path": "C:\\heavy_summary.json",
        }
        summary_payload = {
            "final_status": "working",
            "execution_mode": verifier.DEFAULT_SHADOW_EXECUTION_MODE,
            "inputs": {
                "retrieval_packet": {
                    "latest_memory_id": "memory-1",
                    "semantic_sha256": "sha-1",
                }
            },
            "policy": {
                "authoritative_decision_behavior_changed": False,
                "fail_closed_preserved": True,
                "source_of_truth_mutation": False,
                "strategy_logic_mutation": False,
                "production_changes_required": False,
                "governor_mutated": False,
            },
            "planner": {
                "controlled_retrieval_comparison": {
                    "observations": {
                        "diff": {
                            "changed_fields": ["mechanism_hypothesis", "selection_rationale"],
                            "proposal_content_fields_changed": [],
                            "proposal_content_fields_preserved": True,
                        },
                        "authoritative": {
                            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                        },
                        "candidate": {
                            "status": "completed",
                            "error": "",
                            "response_id": "planner-candidate",
                            "response_status": "completed",
                            "response_model": "gpt-test",
                            "usage": {"input_tokens": 140, "output_tokens": 35, "total_tokens": 175},
                        },
                    },
                    "authoritative_prompt_metrics": {
                        "estimated_input_tokens_char_div4": 200,
                        "json_char_count": 800,
                        "utf8_byte_count": 800,
                        "payload_sha256": "planner-authoritative",
                    },
                    "candidate_prompt_metrics": {
                        "estimated_input_tokens_char_div4": 260,
                        "json_char_count": 1040,
                        "utf8_byte_count": 1040,
                        "payload_sha256": "planner-candidate",
                    },
                    "candidate_prompt_mode": "compact",
                    "retrieval_prompt_observability": {
                        "selected_mode": "compact",
                        "full_retrieval_mode": {
                            "prompt_metrics": {
                                "estimated_input_tokens_char_div4": 360,
                                "json_char_count": 1440,
                                "utf8_byte_count": 1440,
                                "payload_sha256": "planner-full",
                            }
                        },
                        "compact_retrieval_mode": {
                            "prompt_metrics": {
                                "estimated_input_tokens_char_div4": 260,
                                "json_char_count": 1040,
                                "utf8_byte_count": 1040,
                                "payload_sha256": "planner-candidate",
                            }
                        },
                        "token_delta_impact": {
                            "full_vs_authoritative": {
                                "estimated_input_tokens_char_div4_delta": 160,
                                "json_char_count_delta": 640,
                                "utf8_byte_count_delta": 640,
                            },
                            "compact_vs_authoritative": {
                                "estimated_input_tokens_char_div4_delta": 60,
                                "json_char_count_delta": 240,
                                "utf8_byte_count_delta": 240,
                            },
                            "compact_vs_full": {
                                "estimated_input_tokens_char_div4_delta": -100,
                                "json_char_count_delta": -400,
                                "utf8_byte_count_delta": -400,
                            },
                        },
                    },
                    "decision_behavior_changed": False,
                    "fail_closed_preserved": True,
                },
                "openai_hook": {
                    "network_call": "completed",
                    "response_id": "planner-authoritative",
                    "response_status": "completed",
                    "response_model": "gpt-test",
                    "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                },
                "passive_retrieval_comparison": {
                    "comparison_bucket": "with_retrieval_packet",
                    "retrieval_packet_present": True,
                    "retrieval_packet_status": "loaded",
                    "latest_memory_id": "memory-1",
                    "semantic_sha256": "sha-1",
                    "load_error": "",
                },
            },
            "critic": {
                "controlled_retrieval_comparison": {
                    "observations": {
                        "diff": {
                            "changed_fields": ["policy_alignment_note", "recommended_reason"],
                            "proposal_content_fields_changed": [],
                            "proposal_content_fields_preserved": True,
                        },
                        "authoritative": {
                            "usage": {"input_tokens": 90, "output_tokens": 18, "total_tokens": 108},
                        },
                        "candidate": {
                            "status": "completed",
                            "error": "",
                            "response_id": "critic-candidate",
                            "response_status": "completed",
                            "response_model": "gpt-test",
                            "usage": {"input_tokens": 130, "output_tokens": 28, "total_tokens": 158},
                        },
                    },
                    "authoritative_prompt_metrics": {
                        "estimated_input_tokens_char_div4": 180,
                        "json_char_count": 720,
                        "utf8_byte_count": 720,
                        "payload_sha256": "critic-authoritative",
                    },
                    "candidate_prompt_metrics": {
                        "estimated_input_tokens_char_div4": 240,
                        "json_char_count": 960,
                        "utf8_byte_count": 960,
                        "payload_sha256": "critic-candidate",
                    },
                    "candidate_prompt_mode": "compact",
                    "retrieval_prompt_observability": {
                        "selected_mode": "compact",
                        "full_retrieval_mode": {
                            "prompt_metrics": {
                                "estimated_input_tokens_char_div4": 330,
                                "json_char_count": 1320,
                                "utf8_byte_count": 1320,
                                "payload_sha256": "critic-full",
                            }
                        },
                        "compact_retrieval_mode": {
                            "prompt_metrics": {
                                "estimated_input_tokens_char_div4": 240,
                                "json_char_count": 960,
                                "utf8_byte_count": 960,
                                "payload_sha256": "critic-candidate",
                            }
                        },
                        "token_delta_impact": {
                            "full_vs_authoritative": {
                                "estimated_input_tokens_char_div4_delta": 150,
                                "json_char_count_delta": 600,
                                "utf8_byte_count_delta": 600,
                            },
                            "compact_vs_authoritative": {
                                "estimated_input_tokens_char_div4_delta": 60,
                                "json_char_count_delta": 240,
                                "utf8_byte_count_delta": 240,
                            },
                            "compact_vs_full": {
                                "estimated_input_tokens_char_div4_delta": -90,
                                "json_char_count_delta": -360,
                                "utf8_byte_count_delta": -360,
                            },
                        },
                    },
                    "decision_behavior_changed": False,
                    "fail_closed_preserved": True,
                },
                "openai_review": {
                    "network_call": "completed",
                    "response_id": "critic-authoritative",
                    "response_status": "completed",
                    "response_model": "gpt-test",
                    "usage": {"input_tokens": 90, "output_tokens": 18, "total_tokens": 108},
                },
                "passive_retrieval_comparison": {
                    "comparison_bucket": "with_retrieval_packet",
                    "retrieval_packet_present": True,
                    "retrieval_packet_status": "loaded",
                    "latest_memory_id": "memory-1",
                    "semantic_sha256": "sha-1",
                    "load_error": "",
                },
            },
        }

        root = self.temp_root
        with mock.patch.object(batch_eval.verifier, "evaluate_verification_case", return_value=summary_payload):
            built = batch_eval.build_summary(
                retrieval_root=root,
                planner_input_root=root,
                heavy_validation_root=root,
                output_path=root / "summary.json",
                markdown_path=root / "summary.md",
                compact_summary_path=root / "manual_review.csv",
                execution_mode=verifier.DEFAULT_SHADOW_EXECUTION_MODE,
                requested_family_ids=["family.alpha"],
                requested_cycle_labels=["cycle_one"],
                packets=[],
                skipped=[],
                discovery_details={},
                cases=[case],
            )

        self.assertEqual(built["schema_version"], "trendatlas.shadow_batch_eval.v3")
        self.assertEqual(
            built["summary"]["planner_reasoning_field_differences_frequency"],
            {"mechanism_hypothesis": 1, "selection_rationale": 1},
        )
        self.assertEqual(
            built["summary"]["critic_reasoning_field_differences_frequency"],
            {"policy_alignment_note": 1, "recommended_reason": 1},
        )
        self.assertEqual(
            built["summary"]["token_deltas"]["planner"]["response_output_tokens_delta"]["sum"],
            15,
        )
        self.assertEqual(
            built["summary"]["token_deltas"]["critic"]["response_output_tokens_delta"]["sum"],
            10,
        )
        self.assertEqual(
            built["summary"]["token_deltas"]["planner"]["compact_vs_full_prompt_estimated_input_tokens_delta"]["sum"],
            -100,
        )
        self.assertEqual(
            built["summary"]["token_deltas"]["critic"]["compact_vs_full_prompt_estimated_input_tokens_delta"]["sum"],
            -90,
        )
        self.assertEqual(built["summary"]["planner_reasoning_changed_decision_identical_cases"], 1)
        self.assertEqual(built["summary"]["critic_reasoning_changed_decision_identical_cases"], 1)
        self.assertEqual(built["summary"]["reasoning_changed_decision_identical_case_count"], 1)
        self.assertEqual(
            built["compact_summary_rows"],
            [
                {
                    "family_id": "family.alpha",
                    "cycle_label": "cycle_one",
                    "status": "working",
                    "fail_closed_preserved": True,
                    "planner_reasoning_fields_changed": "mechanism_hypothesis,selection_rationale",
                    "planner_decision_fields_changed": "",
                    "planner_reasoning_changed": True,
                    "planner_decision_stayed_identical": True,
                    "planner_reasoning_changed_decision_identical": True,
                    "planner_prompt_input_token_delta": 60,
                    "planner_input_token_delta": 40,
                    "planner_output_token_delta": 15,
                    "planner_total_token_delta": 55,
                    "critic_reasoning_fields_changed": "policy_alignment_note,recommended_reason",
                    "critic_decision_fields_changed": "",
                    "critic_reasoning_changed": True,
                    "critic_decision_stayed_identical": True,
                    "critic_reasoning_changed_decision_identical": True,
                    "critic_prompt_input_token_delta": 60,
                    "critic_input_token_delta": 40,
                    "critic_output_token_delta": 10,
                    "critic_total_token_delta": 50,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
