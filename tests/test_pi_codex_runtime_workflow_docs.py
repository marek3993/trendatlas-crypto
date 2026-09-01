import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class TestPiCodexRuntimeWorkflowDocs(unittest.TestCase):
    def test_agents_md_exists_and_contains_required_rules(self):
        path = ROOT / "AGENTS.md"
        self.assertTrue(path.exists(), "AGENTS.md must exist at repo root")

        text = path.read_text(encoding="utf-8")
        required_snippets = [
            "source_of_truth/README.md",
            "source_of_truth/master_state.md",
            "source_of_truth/chat_roles.md",
            "source_of_truth/project_truth.json",
            "source_of_truth/export_contract.json",
            "source_of_truth/paths_registry.json",
            "source_of_truth/current_issues.md",
            "canonical/script_registry.json",
            "canonical/output_registry.json",
            "canonical/registry_workflow.md",
            "source_of_truth/pi_codex_runtime_workflow.md",
            "FILES READ",
            "SOURCE OF TRUTH",
            "exact root cause",
            "exact contract impact",
            "exact files changed",
            "regression test added/updated",
            "forbidden old path checked",
            "validation commands/results",
            "exact git add list",
            "commit message",
            "commit hash",
            "actual_held_asset",
            "current_asset",
            "effective_market_exposure",
            "model equity",
            "paper equity",
            "Do not run long/full refresh unless explicitly approved.",
            "Do not live order unless explicitly approved.",
            "Do not manually edit or commit generated `outputs/*` or `data/*` unless explicitly approved.",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in text]
        self.assertFalse(missing, f"AGENTS.md missing required snippets: {missing}")

    def test_pi_codex_runtime_workflow_contains_required_runbook(self):
        text = read_text("source_of_truth/pi_codex_runtime_workflow.md")
        required_snippets = [
            "Pi repo root = `/opt/market_regime_v1`",
            "Home dashboard root for tablet/dashboard tasks only = `/opt/home_automation`",
            "do NOT run long/full refresh by default",
            "do NOT run `--mode full-refresh` unless explicitly approved",
            "/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_authoritative_producer.py --mode publish-existing",
            "always dry-run before real publish",
            "no live order",
            "no manual authority snapshot edits",
            "no manual generated outputs/data commits outside official authority producer",
            "if `git pull` makes runtime stale, restore approved fresh runtime stash before dry-run",
            "`heavy_refresh_steps=skipped`",
            "`live_order_chain=not_invoked`",
            "scripts/execution/hyperliquid_read_only_snapshot.py",
            "1. `git status`",
            "2. `git fetch origin main`",
            "3. `git pull --rebase origin main`",
            "4. locate fresh stash if runtime stale",
            "5. restore approved runtime bundle only if needed",
            "6. run publish-existing dry-run:",
            "7. only then run real publish:",
            "8. pull published authority commit",
            "9. verify final state",
            "`AUTH attempt status`",
            "`AUTH success model/target`",
            "`target_closed_day_utc`",
            "`dashboard_public_status exists when expected`",
            "`real_account asset/exposure/in_market`",
            "`model_signal preferred_asset/exposure`",
            "`health block_app/block_execution`",
            "`gate would_place_real_order` recorded from current policy/account/signal state",
            "`task name / owner / status / next action / blocker`",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in text]
        self.assertFalse(
            missing,
            f"source_of_truth/pi_codex_runtime_workflow.md missing required snippets: {missing}",
        )

    def test_reference_docs_point_to_pi_codex_runtime_workflow(self):
        reference_docs = [
            "source_of_truth/README.md",
            "source_of_truth/master_state.md",
            "source_of_truth/chat_roles.md",
            "canonical/registry_workflow.md",
        ]

        failures = []
        for relative_path in reference_docs:
            text = read_text(relative_path)
            if "source_of_truth/pi_codex_runtime_workflow.md" not in text:
                failures.append(relative_path)

        self.assertFalse(
            failures,
            f"Reference docs missing pi_codex_runtime_workflow.md link: {failures}",
        )


if __name__ == "__main__":
    unittest.main()
