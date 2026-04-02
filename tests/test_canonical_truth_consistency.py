import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STRATEGY_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json"
STRATEGY_SNAPSHOT_PATH = ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json"
UNIVERSE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_universe_decision.json"
LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"
REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_strategy_decision_and_snapshot_are_consistent():
    decision = load_json(STRATEGY_DECISION_PATH)
    snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

    decision_summary = decision["decision_summary"]
    current_state = snapshot["current_state"]

    assert decision_summary["official_core_production_baseline"] == current_state["official_core_production_baseline"]["value"]
    assert decision_summary["official_universe_winner"] == current_state["official_universe_winner"]["value"]
    assert decision_summary["product_direction"] == current_state["product_direction"]["value"]
    assert decision_summary["live_leverage_truth"] == current_state["live_leverage_truth"]["value"]


def test_universe_decision_matches_strategy_snapshot():
    universe_decision = load_json(UNIVERSE_DECISION_PATH)
    snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

    assert (
        universe_decision["decision_summary"]["official_universe_winner"]
        == snapshot["current_state"]["official_universe_winner"]["value"]
    )

    assert (
        universe_decision["decision_summary"]["reference_baseline"]
        == snapshot["current_state"]["official_core_production_baseline"]["value"]
    )


def test_leverage_decision_matches_strategy_snapshot():
    leverage_decision = load_json(LEVERAGE_DECISION_PATH)
    snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

    assert (
        leverage_decision["decision_summary"]["current_live_leverage_mode"]
        == snapshot["current_state"]["live_leverage_truth"]["value"]
    )


def test_66g_reference_is_not_marked_as_current_universe_winner_or_live_leverage_truth():
    reference_payload = load_json(REF_66G_PATH)
    reference_summary = reference_payload["reference_summary"]

    assert reference_payload["truth_status"] == "reference"
    assert reference_summary["is_current_universe_winner"] is False
    assert reference_summary["is_current_live_leverage_truth"] is False


def test_benchmark_reference_is_not_marked_as_current_live_truth():
    benchmark_payload = load_json(BENCHMARK_REF_PATH)
    reference_summary = benchmark_payload["reference_summary"]

    assert benchmark_payload["truth_status"] == "reference"
    assert reference_summary["is_current_live_truth"] is False


def test_product_direction_mentions_btc_benchmark():
    decision = load_json(STRATEGY_DECISION_PATH)
    assert "BTC benchmark" in decision["decision_summary"]["product_direction"]