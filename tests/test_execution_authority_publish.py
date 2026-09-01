import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts import daily_refresh_app_pipeline as pipeline
from scripts.execution import authority_contract as contract
from scripts.execution import authority_publish_helpers as helpers
from scripts.execution import current_strategy_root_contract as current_strategy_contract
from scripts.execution import materialize_execution_app_exports as materializer
from scripts.execution import run_pi_authoritative_producer as pi_producer
from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
    build_authority_payload,
)

PI_ENV = {
    "MRV1_ENABLE_AUTHORITY_PUBLISH": "1",
    "MRV1_AUTHORITY_MODE": "authoritative",
    "MRV1_AUTOMATIC_PRODUCER_ID": "raspberry_pi",
    "MRV1_REQUIRE_PI_RUNTIME": "1",
    "MRV1_RUNTIME_PLATFORM_SYSTEM": "linux",
    "MRV1_RUNTIME_PLATFORM_MACHINE": "aarch64",
    "MRV1_PUBLISH_HOSTNAME": "pi-unit-test",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestExecutionAuthorityPublish(unittest.TestCase):
    def run_git(
        self,
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
            env=(os.environ | env) if env is not None else None,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"git {' '.join(args)} failed in {cwd}\nstdout={result.stdout}\nstderr={result.stderr}"
            )
        return result

    def make_temp_root(self) -> Path:
        base_dir = ROOT / "outputs" / "_tmp_test_execution_authority_publish"
        base_dir.mkdir(parents=True, exist_ok=True)
        temp_root = base_dir / f"case_{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=False)
        shutil.copytree(ROOT / "source_of_truth", temp_root / "source_of_truth")
        self.addCleanup(shutil.rmtree, temp_root, True)
        return temp_root

    def write_text_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_json_file(self, path: Path, payload: dict) -> None:
        self.write_text_file(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )

    def seed_required_source_of_truth_files(self, temp_root: Path) -> None:
        source_of_truth_dir = temp_root / "source_of_truth"
        source_of_truth_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("project_truth.json", "export_contract.json"):
            target_path = source_of_truth_dir / filename
            if not target_path.exists():
                shutil.copy2(ROOT / "source_of_truth" / filename, target_path)

    def seed_fast_publish_runtime_artifacts(self, temp_root: Path) -> None:
        production_dir = temp_root / "outputs" / "production"
        self.write_json_file(
            production_dir / "current_strategy_snapshot.json",
            {"artifact_type": "current_strategy_snapshot"},
        )
        self.write_text_file(
            production_dir / "current_strategy_timeseries.csv",
            "date,equity\n2026-04-22,1.0\n",
        )
        self.write_json_file(
            production_dir / "current_strategy_diagnostics.json",
            {"artifact_type": "current_strategy_diagnostics"},
        )
        self.write_json_file(
            production_dir / "current_strategy_snapshot.quality.json",
            {"status": "passed"},
        )
        self.write_json_file(
            production_dir / "current_strategy_snapshot.manifest.json",
            {"artifact_type": "current_strategy_snapshot_manifest"},
        )
        self.write_json_file(
            production_dir / "data_health_report.json",
            {"artifact_type": "data_health_report"},
        )
        self.write_json_file(
            production_dir / "data_health_report.quality.json",
            {"status": "passed"},
        )
        self.write_json_file(
            production_dir / "data_health_report.manifest.json",
            {"artifact_type": "data_health_report_manifest"},
        )
        execution_artifacts = {
            "outputs/execution/intents/latest_execution_intent.json": {},
            "outputs/execution/intents/latest_execution_intent_quality.json": {},
            "outputs/execution/intents/latest_execution_intent_manifest.json": {},
            "outputs/execution/live_gate/latest_real_order_gate_decision.json": {},
            "outputs/execution/live_gate/latest_real_order_gate_quality.json": {},
            "outputs/execution/live_gate/latest_real_order_gate_manifest.json": {},
            "outputs/execution/read_only/hyperliquid_account_snapshot.json": {},
            "outputs/execution/read_only/hyperliquid_account_snapshot_quality.json": {},
            "outputs/execution/read_only/hyperliquid_account_snapshot_manifest.json": {},
        }
        for relative_path, payload in execution_artifacts.items():
            self.write_json_file(temp_root / relative_path, payload)

    def seed_fast_publish_script_placeholders(self, temp_root: Path) -> dict[str, Path]:
        script_paths = {
            "pipeline": temp_root / "scripts" / "daily_refresh_app_pipeline.py",
            "current_strategy_build": (
                temp_root / "scripts" / "production" / "build_current_strategy_snapshot.py"
            ),
            "current_strategy_validate": (
                temp_root / "scripts" / "production" / "validate_current_strategy_snapshot.py"
            ),
            "materialize_app_exports": (
                temp_root / "scripts" / "execution" / "materialize_execution_app_exports.py"
            ),
        }
        for path in script_paths.values():
            self.write_text_file(path, "# placeholder\n")
        return script_paths

    def build_minimal_app_product_snapshot_payload(self) -> dict:
        root_contract = current_strategy_contract.load_current_main_strategy_root_contract(
            root=ROOT,
            require_files=False,
        )
        export_contract = load_json(ROOT / "source_of_truth" / "export_contract.json")[
            "app_export_contract"
        ]
        reference_strategy_model = export_contract["reference_strategy_model"]
        reference_source = export_contract["model_sources"][reference_strategy_model]
        trend_barometer_source = export_contract["trend_barometer_source"]
        serialized_root_contract = (
            current_strategy_contract.serialize_current_main_strategy_root_contract(root_contract)
        )
        modified_utc = "2026-04-23T12:00:00Z"
        return {
            "current_main_strategy_root_contract": serialized_root_contract,
            "main_strategy_model": root_contract["main_strategy_model"],
            "reference_strategy_model": reference_strategy_model,
            "main_strategy_metrics": {
                "model": root_contract["main_strategy_model"],
                "switch_count": 0,
                "cash_days_pct": 0.0,
                "btc_days_pct": 100.0,
            },
            "chart_source_paths": {
                "main_strategy": root_contract["canonical_paper_source_path"],
                "reference_strategy": reference_source["paper_path"],
            },
            "source_metadata": {
                "main_strategy_metrics": {
                    "path": root_contract["canonical_metrics_source_path"],
                    "modified_utc": modified_utc,
                    "operational_metrics": {
                        "path": root_contract["canonical_paper_source_path"],
                        "held_state_column": "held_asset",
                        "series_semantics": "homepage_current_main_strategy_held_state_history",
                        "held_state_denominator_rows": 1,
                    },
                },
                "strategy_last_closed_day": {
                    "path": root_contract["canonical_paper_source_path"],
                    "modified_utc": modified_utc,
                },
                "live_public_state": {
                    "path": root_contract["canonical_paper_source_path"],
                    "modified_utc": modified_utc,
                },
                "chart_source_paths": {
                    "main_strategy": {
                        "path": root_contract["canonical_paper_source_path"],
                        "modified_utc": modified_utc,
                    },
                    "reference_strategy": {
                        "path": reference_source["paper_path"],
                        "modified_utc": modified_utc,
                    },
                },
                "trend_barometer_summary": {
                    "path": trend_barometer_source["live_status_path"],
                    "modified_utc": modified_utc,
                },
                "trend_history_source_path": {
                    "path": trend_barometer_source["history_path"],
                    "modified_utc": modified_utc,
                },
                "freshness": {
                    "path": "outputs/execution/freshness/app_freshness_report.json",
                    "modified_utc": modified_utc,
                },
                "freshness_target_closed_day": {
                    "path": "outputs/execution/freshness/app_freshness_report.json",
                    "modified_utc": modified_utc,
                },
            },
            "freshness_target_closed_day": "2026-04-22",
            "strategy_last_closed_day": "2026-04-22",
            "live_public_state": {
                "date": "2026-04-22",
            },
            "trend_history_source_path": trend_barometer_source["history_path"],
        }

    def build_minimal_app_runtime_snapshot_payload(self) -> dict:
        return {
            "latest_available_closed_utc_date": "2026-04-22",
            "latest_strategy_artifact_date": "2026-04-22",
            "latest_wallet_sync_utc": "2026-04-23T10:45:00Z",
            "account_snapshot_as_of_utc": "2026-04-23T10:45:00Z",
            "app_runtime_snapshot_generated_at_utc": "2026-04-23T10:45:00Z",
            "dashboard_public_status": self.build_minimal_dashboard_public_status_payload(),
            "account_snapshot_summary": {
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
            },
        }

    def build_minimal_dashboard_public_status_payload(self) -> dict:
        return {
            "schema_version": 1,
            "closed_day": "2026-04-22",
            "generated_at_utc": "2026-04-23T10:45:00Z",
            "real_account": {
                "asset": "CASH",
                "position_label_sk": "Mimo trhu",
                "exposure_x": 0.0,
                "in_market": False,
                "account_equity_usd": 39.475466,
                "available_balance_usd": 39.475466,
            },
            "execution": {
                "target_asset": "CASH",
                "target_size_pct": 0.0,
                "gate_status": "blocked",
                "would_place_real_order": False,
                "live_order_sent": False,
            },
            "model_signal": {
                "preferred_asset": "BTC",
                "exposure_x": 0.75,
                "label_sk": "ModelovĂ˝ signĂˇl",
                "not_real_wallet_exposure": True,
            },
            "model_performance": {
                "account_24h_pct": 0.0,
                "btc_24h_pct": -0.5,
                "account_vs_btc_24h_pct": 0.5,
                "public_average_annual_growth_pct": 216.86,
                "since_etf_start_cagr_pct": 322.34,
                "since2025_cagr_pct": 251.64,
            },
            "data_health": {
                "reference_closed_day": "2026-04-22",
                "overall_status": "ok",
                "block_app": False,
                "block_execution": False,
            },
            "live_market_state": {
                "btc_24h_pct": -0.5,
                "btc_24h_pct_source": "published_snapshot",
                "btc_24h_pct_expected_live_source": "live_ticker",
                "btc_24h_pct_snapshot_is_not_live": True,
                "published_snapshot_btc_24h_pct": -0.5,
                "account_24h_pct": 0.0,
                "account_vs_btc_24h_pct": 0.5,
            },
            "public_labels_sk": {
                "account_24h": "ĂšÄŤet 24h",
                "account_vs_btc": "ĂšÄŤet vs BTC",
                "real_account": "ReĂˇlny ĂşÄŤet",
                "model_signal": "ModelovĂ˝ signĂˇl",
            },
        }

    def seed_canonical_app_export_artifacts(self, temp_root: Path) -> None:
        self.seed_required_source_of_truth_files(temp_root)
        product_snapshot = self.build_minimal_app_product_snapshot_payload()
        chart_source_paths = product_snapshot["chart_source_paths"]
        metrics_source_path = product_snapshot["source_metadata"]["main_strategy_metrics"]["path"]
        main_paper_path = temp_root / Path(chart_source_paths["main_strategy"])
        main_summary_path = temp_root / Path(metrics_source_path)
        reference_paper_path = temp_root / Path(chart_source_paths["reference_strategy"])
        reference_strategy_model = product_snapshot["reference_strategy_model"]
        export_contract = load_json(temp_root / "source_of_truth" / "export_contract.json")[
            "app_export_contract"
        ]
        reference_live_status_path = temp_root / Path(
            export_contract["model_sources"][reference_strategy_model]["live_status_path"]
        )
        trend_barometer_source = export_contract["trend_barometer_source"]
        phase66g_live_status_path = temp_root / Path(trend_barometer_source["live_status_path"])
        trend_history_path = temp_root / Path(trend_barometer_source["history_path"])
        freshness_report_path = (
            temp_root / "outputs" / "execution" / "freshness" / "app_freshness_report.json"
        )

        main_paper_path.parent.mkdir(parents=True, exist_ok=True)
        main_summary_path.parent.mkdir(parents=True, exist_ok=True)
        reference_paper_path.parent.mkdir(parents=True, exist_ok=True)
        reference_live_status_path.parent.mkdir(parents=True, exist_ok=True)
        phase66g_live_status_path.parent.mkdir(parents=True, exist_ok=True)
        trend_history_path.parent.mkdir(parents=True, exist_ok=True)
        freshness_report_path.parent.mkdir(parents=True, exist_ok=True)

        main_paper_path.write_text(
            "date,held_asset,equity\n2026-04-22,BTC,1.0\n",
            encoding="utf-8",
        )
        main_summary_path.write_text(
            "model,latest_available_date,total_return_pct,cagr_pct,max_drawdown_pct,since2023_cagr_pct,since2025_cagr_pct,sharpe,sortino,switch_count,cash_days_pct,btc_days_pct\n"
            f"{product_snapshot['main_strategy_model']},2026-04-22,0,0,0,0,0,0,0,0,0,100\n",
            encoding="utf-8",
        )
        reference_paper_path.write_text(
            "date,equity\n2026-04-22,1.0\n",
            encoding="utf-8",
        )
        reference_live_status_path.write_text(
            f"model,latest_available_date\n{reference_strategy_model},2026-04-22\n",
            encoding="utf-8",
        )
        phase66g_live_status_path.write_text(
            "latest_available_date,trend_calc_date\n2026-04-22,2026-04-22\n",
            encoding="utf-8",
        )
        trend_history_path.write_text(
            "trend_calc_date\n2026-04-22\n",
            encoding="utf-8",
        )
        freshness_report_path.write_text(
            json.dumps(
                {
                    "latest_closed_utc_date": "2026-04-22",
                    "status": "ok",
                    "errors": [],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def seed_app_snapshots(self, temp_root: Path) -> None:
        self.seed_canonical_app_export_artifacts(temp_root)
        app_snapshot_dir = temp_root / "outputs" / "execution" / "app_snapshot"
        app_snapshot_dir.mkdir(parents=True, exist_ok=True)
        (app_snapshot_dir / "app_product_snapshot.json").write_text(
            json.dumps(self.build_minimal_app_product_snapshot_payload()),
            encoding="utf-8",
        )
        (app_snapshot_dir / "app_runtime_snapshot.json").write_text(
            json.dumps(self.build_minimal_app_runtime_snapshot_payload()),
            encoding="utf-8",
        )
        (app_snapshot_dir / "dashboard_public_status.json").write_text(
            json.dumps(self.build_minimal_dashboard_public_status_payload()),
            encoding="utf-8",
        )
        (app_snapshot_dir / "dashboard_public_chart_timeseries.csv").write_text(
            "date,live_strategy_index,live_strategy_exposure_x,live_strategy_return_net,live_strategy_vs_btc_return,live_strategy_source,strategy_execution_index,model_index,btc_index,strategy_execution_exposure_x,strategy_execution_return_net,strategy_execution_vs_btc_return,strategy_execution_source,model_authorized_exposure_x,model_authorized_return_net,model_authorized_return_gross,model_transition_cost,model_asset_transition_day,real_account_index,real_account_exposure_x,real_account_return_net,real_account_vs_btc_return,real_account_source,chart_scope\n"
            "2026-04-22,1.0,0.0,0.0,0.0,pre_live,1.0,1.0,1.0,0.0,0.0,0.0,pre_live,0.0,0.0,0.0,0.0,False,1.0,0.0,0.0,0.0,real_account_flat_no_history,real_account_flat_no_history\n",
            encoding="utf-8",
        )
        (app_snapshot_dir / "dashboard_public_status.quality.json").write_text(
            json.dumps({"status": "ok", "error_count": 0, "errors": [], "checks": {}}),
            encoding="utf-8",
        )
        (app_snapshot_dir / "dashboard_public_status.manifest.json").write_text(
            json.dumps({"status": "ok", "output_files": []}),
            encoding="utf-8",
        )

    def patch_helper_paths(self, stack: ExitStack, temp_root: Path) -> None:
        pipeline_script = temp_root / "scripts" / "daily_refresh_app_pipeline.py"
        pipeline_script.parent.mkdir(parents=True, exist_ok=True)
        pipeline_script.write_text("# helper test placeholder\n", encoding="utf-8")
        temp_root_contract = current_strategy_contract.load_current_main_strategy_root_contract(
            root=temp_root,
            require_files=False,
        )
        stack.enter_context(mock.patch.object(helpers, "ROOT", temp_root))
        stack.enter_context(
            mock.patch.object(
                helpers,
                "APP_PRODUCT_SNAPSHOT_PATH",
                temp_root / "outputs" / "execution" / "app_snapshot" / "app_product_snapshot.json",
            )
        )
        stack.enter_context(
            mock.patch.object(
                helpers,
                "APP_RUNTIME_SNAPSHOT_PATH",
                temp_root / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json",
            )
        )
        stack.enter_context(mock.patch.object(helpers, "PIPELINE_SCRIPT_PATH", pipeline_script))
        stack.enter_context(
            mock.patch.object(
                helpers,
                "load_current_main_strategy_root_contract",
                return_value=temp_root_contract,
            )
        )

    def build_state(self, temp_root: Path, run_id: str, started_at_utc: str) -> dict:
        run_dir = temp_root / "outputs" / "app_refresh_pipeline" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return helpers.build_authority_publish_state(
            run_id=run_id,
            run_dir=run_dir,
            refresh_started_at_utc=started_at_utc,
            target_closed_day_utc="2026-04-22",
            env=PI_ENV,
        )

    def build_payload_pair(self) -> tuple[dict, dict]:
        extra_fields = contract.build_authority_extra_fields(
            run_id="20260423_101500",
            source_manifest_path="outputs/app_refresh_pipeline/20260423_101500/app_refresh_pipeline_manifest.json",
            authority_role="pi_only_authoritative_producer",
            automatic_producer_id="raspberry_pi",
            latest_successful_snapshot_path="outputs/execution/authority/latest_successful_snapshot.json",
            latest_attempt_status_path="outputs/execution/authority/latest_attempt_status.json",
            generated_at_utc="2026-04-23T10:45:00Z",
            attempt_stage="daily_refresh_app_pipeline",
            attempt_stage_status="success",
            stage_history=[],
        )
        attempt_payload = build_authority_payload(
            artifact_type=ATTEMPT_STATUS_ARTIFACT_TYPE,
            target_closed_day_utc="2026-04-22",
            latest_available_closed_utc_day="2026-04-22",
            refresh_started_at_utc="2026-04-23T10:00:00Z",
            refresh_finished_at_utc="2026-04-23T10:45:00Z",
            latest_authoritative_attempt_status="success",
            latest_authoritative_attempt_error=None,
            strategy_artifact_closed_day_utc="2026-04-22",
            extra_fields=extra_fields,
        )
        success_payload = build_authority_payload(
            artifact_type=SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
            target_closed_day_utc="2026-04-22",
            latest_available_closed_utc_day="2026-04-22",
            refresh_started_at_utc="2026-04-23T10:00:00Z",
            refresh_finished_at_utc="2026-04-23T10:45:00Z",
            latest_authoritative_attempt_status="success",
            latest_authoritative_attempt_error=None,
            strategy_artifact_closed_day_utc="2026-04-22",
            extra_fields=extra_fields,
        )
        return attempt_payload, success_payload

    def build_pi_repo_env(self, temp_root: Path) -> dict[str, str]:
        env = pi_producer.build_pi_authoritative_env()
        env["MRV1_AUTHORITY_PUBLISH_TREE"] = str(
            temp_root.parent / f"{temp_root.name}__authority_publish"
        )
        env["MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS"] = "3"
        env["MRV1_AUTHORITY_GIT_USER_NAME"] = "Pi Authority Publisher"
        env["MRV1_AUTHORITY_GIT_USER_EMAIL"] = "pi-authority@example.com"
        return env

    def seed_authority_payloads(
        self,
        temp_root: Path,
        *,
        run_id: str,
        attempt_status: str,
        include_snapshot: bool,
    ) -> tuple[Path, Path]:
        authority_dir = temp_root / "outputs" / "execution" / "authority"
        authority_dir.mkdir(parents=True, exist_ok=True)
        self.seed_fast_publish_runtime_artifacts(temp_root)
        self.seed_app_snapshots(temp_root)
        extra_fields = contract.build_authority_extra_fields(
            run_id=run_id,
            source_manifest_path=(
                f"outputs/app_refresh_pipeline/{run_id}/app_refresh_pipeline_manifest.json"
            ),
            authority_role="pi_only_authoritative_producer",
            automatic_producer_id="raspberry_pi",
            latest_successful_snapshot_path="outputs/execution/authority/latest_successful_snapshot.json",
            latest_attempt_status_path="outputs/execution/authority/latest_attempt_status.json",
            generated_at_utc="2026-04-23T10:45:00Z",
            attempt_stage="daily_refresh_app_pipeline",
            attempt_stage_status="success" if attempt_status == "success" else "failed",
            stage_history=[],
            app_product_snapshot=self.build_minimal_app_product_snapshot_payload(),
            app_runtime_snapshot=self.build_minimal_app_runtime_snapshot_payload(),
        )
        error = None if attempt_status == "success" else "simulated_failure"
        attempt_payload = build_authority_payload(
            artifact_type=ATTEMPT_STATUS_ARTIFACT_TYPE,
            target_closed_day_utc="2026-04-22",
            latest_available_closed_utc_day="2026-04-22",
            refresh_started_at_utc="2026-04-23T10:00:00Z",
            refresh_finished_at_utc="2026-04-23T10:45:00Z",
            latest_authoritative_attempt_status=attempt_status,
            latest_authoritative_attempt_error=error,
            strategy_artifact_closed_day_utc="2026-04-22" if attempt_status == "success" else None,
            extra_fields=extra_fields,
        )
        attempt_path = authority_dir / "latest_attempt_status.json"
        attempt_path.write_text(
            json.dumps(attempt_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        snapshot_path = authority_dir / "latest_successful_snapshot.json"
        if include_snapshot:
            success_payload = build_authority_payload(
                artifact_type=SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
                target_closed_day_utc="2026-04-22",
                latest_available_closed_utc_day="2026-04-22",
                refresh_started_at_utc="2026-04-23T10:00:00Z",
                refresh_finished_at_utc="2026-04-23T10:45:00Z",
                latest_authoritative_attempt_status="success",
                latest_authoritative_attempt_error=None,
                strategy_artifact_closed_day_utc="2026-04-22",
                extra_fields=extra_fields,
            )
            snapshot_path.write_text(
                json.dumps(success_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        return attempt_path, snapshot_path

    def test_materialize_runtime_snapshot_only_writes_dashboard_public_status_file(self):
        temp_root = self.make_temp_root()
        app_snapshot_dir = temp_root / "outputs" / "execution" / "app_snapshot"
        dashboard_path = app_snapshot_dir / "dashboard_public_status.json"
        chart_path = app_snapshot_dir / "dashboard_public_chart_timeseries.csv"
        quality_path = app_snapshot_dir / "dashboard_public_status.quality.json"
        manifest_path = app_snapshot_dir / "dashboard_public_status.manifest.json"
        runtime_path = app_snapshot_dir / "app_runtime_snapshot.json"
        runtime_snapshot = self.build_minimal_app_runtime_snapshot_payload()

        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "parse_args",
                    return_value=argparse.Namespace(runtime_snapshot_only=True),
                )
            )
            stack.enter_context(mock.patch.object(materializer, "ensure_dirs", return_value=None))
            stack.enter_context(mock.patch.object(materializer, "log", return_value=None))
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "DASHBOARD_PUBLIC_STATUS_PATH",
                    dashboard_path,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH",
                    chart_path,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "DASHBOARD_PUBLIC_STATUS_QUALITY_PATH",
                    quality_path,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "DASHBOARD_PUBLIC_STATUS_MANIFEST_PATH",
                    manifest_path,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "APP_RUNTIME_SNAPSHOT_PATH",
                    runtime_path,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    materializer,
                    "build_runtime_snapshot",
                    return_value=runtime_snapshot,
                )
            )
            materializer.main()

        self.assertTrue(dashboard_path.exists())
        self.assertTrue(chart_path.exists())
        self.assertTrue(quality_path.exists())
        self.assertTrue(manifest_path.exists())
        self.assertTrue(runtime_path.exists())
        self.assertEqual(
            load_json(dashboard_path),
            runtime_snapshot["dashboard_public_status"],
        )

    def test_fast_publish_requires_all_dashboard_public_app_snapshot_artifacts(self):
        required_paths = {
            path.resolve().relative_to(ROOT.resolve()).as_posix()
            for path in pi_producer.FAST_MODE_REQUIRED_APP_SNAPSHOT_ARTIFACTS
        }

        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.json",
            required_paths,
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_chart_timeseries.csv",
            required_paths,
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.quality.json",
            required_paths,
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.manifest.json",
            required_paths,
        )

    def test_build_publish_existing_dry_run_publish_result_includes_dashboard_public_status_pathspec(
        self,
    ):
        temp_root = self.make_temp_root()
        self.seed_authority_payloads(
            temp_root,
            run_id="20260423_104500",
            attempt_status="success",
            include_snapshot=True,
        )
        env = self.build_pi_repo_env(temp_root)
        attempt_payload = load_json(
            temp_root / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
        )
        success_payload = load_json(
            temp_root
            / "outputs"
            / "execution"
            / "authority"
            / "latest_successful_snapshot.json"
        )

        result = pi_producer.build_publish_existing_dry_run_publish_result(
            root=temp_root,
            env=env,
            attempt_payload=attempt_payload,
            success_payload=success_payload,
        )

        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.json",
            result["pathspecs"],
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_chart_timeseries.csv",
            result["pathspecs"],
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.quality.json",
            result["pathspecs"],
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.manifest.json",
            result["pathspecs"],
        )

    def test_successful_publish_writes_both_authority_files_with_utc_and_local_fields(self):
        temp_root = self.make_temp_root()
        self.seed_app_snapshots(temp_root)

        with ExitStack() as stack:
            self.patch_helper_paths(stack, temp_root)
            state = self.build_state(
                temp_root,
                run_id="20260423_100000",
                started_at_utc="2026-04-23T10:00:00Z",
            )

            start_result = helpers.publish_authority_refresh_started(state, env=PI_ENV)
            success_result = helpers.publish_authority_refresh_success(
                state,
                refresh_finished_at_utc="2026-04-23T10:45:00Z",
                env=PI_ENV,
            )

        authority_dir = temp_root / "outputs" / "execution" / "authority"
        attempt_path = authority_dir / "latest_attempt_status.json"
        snapshot_path = authority_dir / "latest_successful_snapshot.json"
        attempt_payload = load_json(attempt_path)
        success_payload = load_json(snapshot_path)

        self.assertTrue(start_result["published"])
        self.assertTrue(success_result["published"])
        self.assertTrue(success_result["successful_snapshot_written"])
        self.assertEqual(
            attempt_payload["artifact_type"],
            ATTEMPT_STATUS_ARTIFACT_TYPE,
        )
        self.assertEqual(
            success_payload["artifact_type"],
            SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
        )
        self.assertEqual(attempt_payload["run_id"], "20260423_100000")
        self.assertEqual(success_payload["run_id"], "20260423_100000")
        self.assertEqual(attempt_payload["display_timezone"], "Europe/Bratislava")
        self.assertEqual(success_payload["display_timezone"], "Europe/Bratislava")
        self.assertEqual(
            attempt_payload["refresh_started_at_local"],
            "2026-04-23T12:00:00+02:00",
        )
        self.assertEqual(
            attempt_payload["refresh_finished_at_local"],
            "2026-04-23T12:45:00+02:00",
        )
        self.assertEqual(
            success_payload["refresh_finished_at_local"],
            "2026-04-23T12:45:00+02:00",
        )
        self.assertEqual(
            attempt_payload["generated_at_local"],
            "2026-04-23T12:45:00+02:00",
        )
        self.assertEqual(
            success_payload["generated_at_local"],
            "2026-04-23T12:45:00+02:00",
        )

    def test_failed_publish_updates_attempt_only_and_preserves_previous_snapshot(self):
        temp_root = self.make_temp_root()
        self.seed_app_snapshots(temp_root)

        with ExitStack() as stack:
            self.patch_helper_paths(stack, temp_root)

            prior_state = self.build_state(
                temp_root,
                run_id="20260423_090000",
                started_at_utc="2026-04-23T09:00:00Z",
            )
            helpers.publish_authority_refresh_started(prior_state, env=PI_ENV)
            helpers.publish_authority_refresh_success(
                prior_state,
                refresh_finished_at_utc="2026-04-23T09:30:00Z",
                env=PI_ENV,
            )

            snapshot_path = temp_root / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
            original_snapshot_text = snapshot_path.read_text(encoding="utf-8")

            failed_state = self.build_state(
                temp_root,
                run_id="20260423_110000",
                started_at_utc="2026-04-23T11:00:00Z",
            )
            helpers.publish_authority_refresh_started(failed_state, env=PI_ENV)
            failure_result = helpers.publish_authority_refresh_failure(
                failed_state,
                refresh_finished_at_utc="2026-04-23T11:15:00Z",
                error="simulated_failure",
                env=PI_ENV,
            )

        attempt_path = temp_root / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
        attempt_payload = load_json(attempt_path)
        snapshot_payload = load_json(snapshot_path)

        self.assertTrue(failure_result["published"])
        self.assertFalse(failure_result["successful_snapshot_written"])
        self.assertEqual(
            attempt_payload["latest_authoritative_attempt_status"],
            "failed",
        )
        self.assertEqual(
            attempt_payload["latest_authoritative_attempt_error"],
            "simulated_failure",
        )
        self.assertEqual(attempt_payload["run_id"], "20260423_110000")
        self.assertEqual(snapshot_payload["run_id"], "20260423_090000")
        self.assertEqual(
            snapshot_path.read_text(encoding="utf-8"),
            original_snapshot_text,
        )

    def test_success_publish_restores_previous_snapshot_if_attempt_write_fails(self):
        temp_root = self.make_temp_root()
        paths = contract.authority_paths(temp_root)
        paths["authority_dir"].mkdir(parents=True, exist_ok=True)
        paths["latest_attempt_status"].write_text(
            json.dumps({"run_id": "old_attempt"}, indent=2) + "\n",
            encoding="utf-8",
        )
        paths["latest_successful_snapshot"].write_text(
            json.dumps({"run_id": "old_snapshot"}, indent=2) + "\n",
            encoding="utf-8",
        )
        previous_attempt_text = paths["latest_attempt_status"].read_text(encoding="utf-8")
        previous_snapshot_text = paths["latest_successful_snapshot"].read_text(encoding="utf-8")
        attempt_payload, success_payload = self.build_payload_pair()

        def flaky_atomic_write_json(path: Path, payload: dict) -> None:
            if Path(path).name == "latest_successful_snapshot.json":
                contract.atomic_write_text(
                    path,
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                )
                return
            raise OSError("simulated_attempt_write_failure")

        with mock.patch.object(
            contract,
            "atomic_write_json",
            side_effect=flaky_atomic_write_json,
        ):
            with self.assertRaises(OSError):
                contract.publish_authority_artifacts(
                    attempt_payload,
                    success_payload,
                    root=temp_root,
                    env=PI_ENV,
                )

        self.assertEqual(
            paths["latest_attempt_status"].read_text(encoding="utf-8"),
            previous_attempt_text,
        )
        self.assertEqual(
            paths["latest_successful_snapshot"].read_text(encoding="utf-8"),
            previous_snapshot_text,
        )

    def test_pipeline_does_not_publish_success_before_post_strategy_step_succeeds(self):
        temp_output_dir = self.make_temp_root()
        publish_success = mock.Mock(
            return_value={
                "published": True,
                "successful_snapshot_written": True,
                "reason": None,
            }
        )
        publish_failure = mock.Mock(
            return_value={
                "published": True,
                "successful_snapshot_written": False,
                "reason": None,
            }
        )

        def fake_run_step_and_persist(
            manifest: dict,
            run_dir: Path,
            step_name: str,
            script_path: Path,
            env: dict[str, str],
            step_logs_dir: Path,
            script_args: list[str] | None = None,
        ) -> dict:
            result = {
                "step_name": step_name,
                "script_path": str(script_path),
                "returncode": 0,
            }
            manifest["steps"].append(result)
            return result

        def fake_run_heavy_phase_with_freshness_fast_path(
            manifest: dict,
            run_dir: Path,
            step_name: str,
            script_path: Path,
            env: dict[str, str],
            step_logs_dir: Path,
            script_args: list[str] | None = None,
        ) -> dict:
            return fake_run_step_and_persist(
                manifest,
                run_dir,
                step_name,
                script_path,
                env,
                step_logs_dir,
                script_args=script_args,
            )

        authority_state = {
            "run_id": "20260423_100000",
            "refresh_started_at_utc": "2026-04-23T10:00:00Z",
            "target_closed_day_utc": "2026-04-22",
            "latest_available_closed_utc_day": "2026-04-22",
            "authority_mode": "pi_only_authoritative_producer",
            "latest_attempt_status_path": "outputs/execution/authority/latest_attempt_status.json",
            "latest_successful_snapshot_path": "outputs/execution/authority/latest_successful_snapshot.json",
            "pipeline_script_path": "scripts/daily_refresh_app_pipeline.py",
            "stage_history": [],
        }

        with mock.patch.object(
            pipeline,
            "OUTPUT_DIR",
            temp_output_dir / "outputs" / "app_refresh_pipeline",
        ), mock.patch.object(
            pipeline,
            "parse_args",
            return_value=argparse.Namespace(
                skip_legacy_refresh=False,
                skip_macro_refresh=False,
                skip_top100_refresh=False,
            ),
        ), mock.patch.object(
            pipeline,
            "build_env",
            return_value=dict(PI_ENV),
        ), mock.patch.object(
            pipeline,
            "build_authority_publish_state",
            return_value=dict(authority_state),
        ), mock.patch.object(
            pipeline,
            "build_authority_manifest_stub",
            return_value={"status": "NOT_RUN"},
        ), mock.patch.object(
            pipeline,
            "build_raw_skip_preflight",
            return_value={
                "target_last_closed_date": "2026-04-22",
                "skip_legacy_refresh": False,
                "skip_top100_refresh": False,
                "status": "OK",
                "checks": {},
                "errors": [],
            },
        ), mock.patch.object(
            pipeline,
            "publish_authority_refresh_started",
            return_value={
                "published": True,
                "successful_snapshot_written": False,
                "reason": None,
            },
        ), mock.patch.object(
            pipeline,
            "publish_authority_refresh_success",
            publish_success,
        ), mock.patch.object(
            pipeline,
            "publish_authority_refresh_failure",
            publish_failure,
        ), mock.patch.object(
            pipeline,
            "run_step_and_persist",
            side_effect=fake_run_step_and_persist,
        ), mock.patch.object(
            pipeline,
            "run_heavy_phase_with_freshness_fast_path",
            side_effect=fake_run_heavy_phase_with_freshness_fast_path,
        ), mock.patch.object(
            pipeline,
            "verify_required_outputs",
            return_value=[],
        ), mock.patch.object(
            pipeline,
            "load_json",
            return_value={},
        ), mock.patch.object(
            pipeline,
            "run_post_strategy_runtime_refresh",
            side_effect=RuntimeError("post_strategy_failed"),
        ), mock.patch.object(
            pipeline,
            "run_non_fatal_post_step",
            return_value={"status": "OK"},
        ), mock.patch.object(
            pipeline,
            "latest_closed_utc_date",
            return_value="2026-04-22",
        ), mock.patch.object(
            pipeline,
            "now_utc",
            return_value="2026-04-23T10:00:00Z",
        ):
            with self.assertRaisesRegex(RuntimeError, "post_strategy_failed"):
                pipeline.main()

        publish_success.assert_not_called()
        publish_failure.assert_called_once()

    def test_pi_repo_publish_commits_and_pushes_authority_files_from_clean_publish_tree(self):
        temp_root = self.make_temp_root()
        self.seed_authority_payloads(
            temp_root,
            run_id="20260423_104500",
            attempt_status="success",
            include_snapshot=True,
        )
        env = self.build_pi_repo_env(temp_root)
        publish_tree = Path(env["MRV1_AUTHORITY_PUBLISH_TREE"])
        remote_url = "git@github.com:example/market_regime_v1.git"
        git_calls: list[list[str]] = []
        expected_pathspecs = [
            str(path.resolve().relative_to(temp_root.resolve())).replace("\\", "/")
            for path in pi_producer.resolve_authority_publish_paths(temp_root)
        ]

        def fake_run(args, cwd=None, env=None, text=None, capture_output=None, check=None):
            git_calls.append(args)
            if args[:2] == ["git", "clone"]:
                (publish_tree / ".git").mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:4] == ["git", "remote", "get-url", "origin"]:
                if cwd == str(temp_root):
                    return subprocess.CompletedProcess(args, 0, remote_url + "\n", "")
                if cwd == str(publish_tree):
                    return subprocess.CompletedProcess(args, 0, remote_url + "\n", "")
            if args[:3] == ["git", "diff", "--cached"]:
                return subprocess.CompletedProcess(args, 1, "", "")
            if args[:2] == ["git", "rev-parse"]:
                return subprocess.CompletedProcess(args, 0, "abc123\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(pi_producer.subprocess, "run", side_effect=fake_run):
            result = pi_producer.publish_authority_artifacts_to_repo(
                root=temp_root,
                env=env,
            )

        self.assertTrue(result["published"])
        self.assertEqual(result["remote"], "origin")
        self.assertEqual(result["branch"], "main")
        self.assertEqual(result["remote_url"], remote_url)
        self.assertEqual(result["publish_tree"], str(publish_tree))
        self.assertEqual(result["push_attempts"], 1)
        self.assertEqual(result["pathspecs"], expected_pathspecs)
        self.assertEqual(result["commit_sha"], "abc123")
        self.assertEqual(
            git_calls,
            [
                ["git", "remote", "get-url", "origin"],
                [
                    "git",
                    "clone",
                    "--origin",
                    "origin",
                    "--branch",
                    "main",
                    "--single-branch",
                    remote_url,
                    str(publish_tree),
                ],
                ["git", "remote", "get-url", "origin"],
                ["git", "fetch", "origin", "main"],
                ["git", "checkout", "-B", "main", "origin/main"],
                ["git", "reset", "--hard", "origin/main"],
                ["git", "clean", "-fd"],
                ["git", "add", "--", *expected_pathspecs],
                ["git", "diff", "--cached", "--quiet", "--", *expected_pathspecs],
                [
                    "git",
                    "commit",
                    "--only",
                    "-m",
                    "Publish Pi authority artifacts: success 2026-04-22 20260423_104500",
                    "--",
                    *expected_pathspecs,
                ],
                ["git", "push", "origin", "HEAD:main"],
                ["git", "rev-parse", "HEAD"],
            ],
        )

    def test_pi_repo_publish_pushes_attempt_only_for_first_failed_run(self):
        temp_root = self.make_temp_root()
        self.seed_authority_payloads(
            temp_root,
            run_id="20260423_111500",
            attempt_status="failed",
            include_snapshot=False,
        )
        env = self.build_pi_repo_env(temp_root)
        publish_tree = Path(env["MRV1_AUTHORITY_PUBLISH_TREE"])
        remote_url = "git@github.com:example/market_regime_v1.git"
        git_calls: list[list[str]] = []

        def fake_run(args, cwd=None, env=None, text=None, capture_output=None, check=None):
            git_calls.append(args)
            if args[:2] == ["git", "clone"]:
                (publish_tree / ".git").mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:4] == ["git", "remote", "get-url", "origin"]:
                if cwd == str(temp_root):
                    return subprocess.CompletedProcess(args, 0, remote_url + "\n", "")
                if cwd == str(publish_tree):
                    return subprocess.CompletedProcess(args, 0, remote_url + "\n", "")
            if args[:3] == ["git", "diff", "--cached"]:
                return subprocess.CompletedProcess(args, 1, "", "")
            if args[:2] == ["git", "rev-parse"]:
                return subprocess.CompletedProcess(args, 0, "def456\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(pi_producer.subprocess, "run", side_effect=fake_run):
            result = pi_producer.publish_authority_artifacts_to_repo(
                root=temp_root,
                env=env,
            )

        self.assertTrue(result["published"])
        self.assertEqual(result["publish_tree"], str(publish_tree))
        self.assertEqual(result["remote_url"], remote_url)
        self.assertEqual(
            result["pathspecs"],
            ["outputs/execution/authority/latest_attempt_status.json"],
        )
        self.assertEqual(
            git_calls,
            [
                ["git", "remote", "get-url", "origin"],
                [
                    "git",
                    "clone",
                    "--origin",
                    "origin",
                    "--branch",
                    "main",
                    "--single-branch",
                    remote_url,
                    str(publish_tree),
                ],
                ["git", "remote", "get-url", "origin"],
                ["git", "fetch", "origin", "main"],
                ["git", "checkout", "-B", "main", "origin/main"],
                ["git", "reset", "--hard", "origin/main"],
                ["git", "clean", "-fd"],
                [
                    "git",
                    "add",
                    "--",
                    "outputs/execution/authority/latest_attempt_status.json",
                ],
                [
                    "git",
                    "diff",
                    "--cached",
                    "--quiet",
                    "--",
                    "outputs/execution/authority/latest_attempt_status.json",
                ],
                [
                    "git",
                    "commit",
                    "--only",
                    "-m",
                    "Publish Pi authority artifacts: failed 2026-04-22 20260423_111500",
                    "--",
                    "outputs/execution/authority/latest_attempt_status.json",
                ],
                ["git", "push", "origin", "HEAD:main"],
                ["git", "rev-parse", "HEAD"],
            ],
        )

    def test_pi_repo_publish_retries_clean_publish_tree_after_remote_drift(self):
        temp_root = self.make_temp_root()
        self.seed_authority_payloads(
            temp_root,
            run_id="20260423_120000",
            attempt_status="success",
            include_snapshot=True,
        )
        env = self.build_pi_repo_env(temp_root)
        publish_tree = Path(env["MRV1_AUTHORITY_PUBLISH_TREE"])
        remote_url = "git@github.com:example/market_regime_v1.git"
        git_calls: list[list[str]] = []
        push_attempts = 0

        def fake_run(args, cwd=None, env=None, text=None, capture_output=None, check=None):
            nonlocal push_attempts
            git_calls.append(args)
            if args[:2] == ["git", "clone"]:
                (publish_tree / ".git").mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:4] == ["git", "remote", "get-url", "origin"]:
                if cwd == str(temp_root):
                    return subprocess.CompletedProcess(args, 0, remote_url + "\n", "")
                if cwd == str(publish_tree):
                    return subprocess.CompletedProcess(args, 0, remote_url + "\n", "")
            if args[:3] == ["git", "diff", "--cached"]:
                return subprocess.CompletedProcess(args, 1, "", "")
            if args[:2] == ["git", "push"]:
                push_attempts += 1
                if push_attempts == 1:
                    return subprocess.CompletedProcess(
                        args,
                        1,
                        "",
                        "! [rejected]        HEAD -> main (non-fast-forward)\nerror: failed to push some refs",
                    )
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:2] == ["git", "rev-parse"]:
                return subprocess.CompletedProcess(args, 0, "fedcba\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(pi_producer.subprocess, "run", side_effect=fake_run):
            result = pi_producer.publish_authority_artifacts_to_repo(
                root=temp_root,
                env=env,
            )

        self.assertTrue(result["published"])
        self.assertEqual(result["push_attempts"], 2)
        self.assertEqual(push_attempts, 2)
        self.assertEqual(git_calls.count(["git", "fetch", "origin", "main"]), 2)
        self.assertEqual(
            git_calls.count(["git", "checkout", "-B", "main", "origin/main"]),
            2,
        )
        self.assertEqual(git_calls.count(["git", "reset", "--hard", "origin/main"]), 2)
        self.assertEqual(git_calls.count(["git", "clean", "-fd"]), 2)

    def test_pi_repo_publish_real_git_flow_commits_only_authority_files_in_clean_publish_tree(self):
        temp_root = self.make_temp_root()
        origin_repo = temp_root.parent / f"{temp_root.name}__origin"
        runtime_root = temp_root.parent / f"{temp_root.name}__runtime"
        publish_tree = temp_root.parent / f"{temp_root.name}__authority_publish"
        self.addCleanup(shutil.rmtree, origin_repo, True)
        self.addCleanup(shutil.rmtree, runtime_root, True)
        self.addCleanup(shutil.rmtree, publish_tree, True)

        origin_repo.mkdir(parents=True, exist_ok=True)
        self.run_git(["init", "--initial-branch=main"], cwd=origin_repo)
        (origin_repo / "README.md").write_text("seed\n", encoding="utf-8")
        self.run_git(["add", "README.md"], cwd=origin_repo)
        commit_env = {
            "GIT_AUTHOR_NAME": "Seed Author",
            "GIT_AUTHOR_EMAIL": "seed@example.com",
            "GIT_COMMITTER_NAME": "Seed Author",
            "GIT_COMMITTER_EMAIL": "seed@example.com",
        }
        self.run_git(["commit", "-m", "seed"], cwd=origin_repo, env=commit_env)

        try:
            self.run_git(["clone", "--branch", "main", str(origin_repo), str(runtime_root)], cwd=temp_root)
        except AssertionError as exc:
            if "couldn't create signal pipe" in str(exc).lower():
                self.skipTest("local git clone transport is blocked in this Windows sandbox")
            raise
        self.seed_required_source_of_truth_files(runtime_root)
        self.seed_authority_payloads(
            runtime_root,
            run_id="20260423_130000",
            attempt_status="success",
            include_snapshot=True,
        )
        env = self.build_pi_repo_env(runtime_root)
        env["MRV1_AUTHORITY_PUBLISH_TREE"] = str(publish_tree)
        push_calls: list[list[str]] = []
        expected_pathspecs = [
            str(path.resolve().relative_to(runtime_root.resolve())).replace("\\", "/")
            for path in pi_producer.resolve_authority_publish_paths(runtime_root)
        ]

        real_run_git_command = pi_producer._run_git_command

        def run_git_command_with_fake_push(
            args: list[str],
            *,
            root: Path,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            if args[:1] == ["push"]:
                push_calls.append(args)
                return subprocess.CompletedProcess(["git", *args], 0, "", "")
            return real_run_git_command(args, root=root, env=env)

        with mock.patch.object(
            pi_producer,
            "_run_git_command",
            side_effect=run_git_command_with_fake_push,
        ):
            result = pi_producer.publish_authority_artifacts_to_repo(
                root=runtime_root,
                env=env,
            )

        self.assertTrue(result["published"])
        self.assertEqual(result["publish_tree"], str(publish_tree))
        self.assertEqual(result["pathspecs"], expected_pathspecs)
        self.assertEqual(push_calls, [["push", "origin", "HEAD:main"]])

        latest_attempt = self.run_git(
            ["show", "HEAD:outputs/execution/authority/latest_attempt_status.json"],
            cwd=publish_tree,
        ).stdout
        latest_snapshot = self.run_git(
            ["show", "HEAD:outputs/execution/authority/latest_successful_snapshot.json"],
            cwd=publish_tree,
        ).stdout
        changed_paths = {
            line.strip()
            for line in self.run_git(
                ["show", "--pretty=", "--name-only", "HEAD"],
                cwd=publish_tree,
            ).stdout.splitlines()
            if line.strip()
        }
        publish_tree_status = self.run_git(["status", "--short"], cwd=publish_tree).stdout.strip()

        self.assertIn('"latest_authoritative_attempt_status": "success"', latest_attempt)
        self.assertIn(f'"artifact_type": "{SUCCESS_SNAPSHOT_ARTIFACT_TYPE}"', latest_snapshot)
        self.assertEqual(
            changed_paths,
            set(expected_pathspecs),
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.json",
            changed_paths,
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_chart_timeseries.csv",
            changed_paths,
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.quality.json",
            changed_paths,
        )
        self.assertIn(
            "outputs/execution/app_snapshot/dashboard_public_status.manifest.json",
            changed_paths,
        )
        self.assertEqual(publish_tree_status, "")

    def test_run_publish_existing_flow_dry_run_skips_heavy_runtime_preview_and_authority_writes(self):
        temp_root = self.make_temp_root()
        attempt_payload, success_payload = self.build_payload_pair()
        authority_state = {
            "run_dir": str(
                temp_root
                / "outputs"
                / "execution"
                / "tmp"
                / "publish_existing_validation"
                / "20260423_104500"
            ),
            "refresh_started_at_utc": "2026-04-23T10:00:00Z",
            "target_closed_day_utc": "2026-04-22",
            "latest_available_closed_utc_day": "2026-04-22",
            "authority_mode": "pi_only_authoritative_producer",
            "pipeline_script_path": "scripts/daily_refresh_app_pipeline.py",
        }
        readiness_bundle = {
            "report": {
                "reference_closed_day_utc": "2026-04-22",
                "summary": {"block_app": False, "block_execution": False},
            },
            "quality": {"status": "passed"},
        }
        publish_preview = {
            "published": False,
            "reason": "dry_run",
            "pathspecs": ["outputs/execution/authority/latest_attempt_status.json"],
        }
        command_labels: list[str] = []

        def fake_run_checked_python_command(script_path, *, env, root, args=None, label):
            command_labels.append(label)
            return subprocess.CompletedProcess([sys.executable, str(script_path)], 0)

        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "run_checked_python_command",
                    side_effect=fake_run_checked_python_command,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "ensure_required_artifacts_exist",
                    return_value=None,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "determine_publish_existing_target_closed_day",
                    return_value="2026-04-22",
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_authority_state",
                    return_value=dict(authority_state),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "load_publish_existing_app_snapshots",
                    return_value=(
                        self.build_minimal_app_product_snapshot_payload(),
                        self.build_minimal_app_runtime_snapshot_payload(),
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_success_payloads",
                    return_value=(attempt_payload, success_payload, dict(authority_state)),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_validation_bundle",
                    return_value=readiness_bundle,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_report_bundle",
                    return_value=readiness_bundle,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "validate_publish_existing_readiness_bundle",
                    return_value=readiness_bundle["report"],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_dry_run_publish_result",
                    return_value=publish_preview,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "publish_existing_authority_success_payloads",
                    side_effect=AssertionError("dry-run must not write authority snapshots"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "publish_authority_artifacts_to_repo",
                    side_effect=AssertionError("dry-run must not invoke repo publish"),
                )
            )
            result = pi_producer.run_publish_existing_flow(
                root=temp_root,
                env=PI_ENV,
                dry_run=True,
            )

        self.assertEqual(
            command_labels,
            [
                "build_current_strategy_snapshot",
                "validate_current_strategy_snapshot",
                "materialize_execution_app_exports",
                "build_execution_intent_from_strategy_exports",
                "prepare_real_order_gate",
                "materialize_execution_app_exports_from_canonical_execution_chain",
                "materialize_execution_app_exports_after_dry_run",
            ],
        )
        self.assertEqual(result["authority_artifact_write"], "skipped_dry_run")
        self.assertEqual(result["runtime_preview_chain"], "not_invoked")
        self.assertEqual(result["live_order_chain"], "not_invoked")
        self.assertEqual(result["authority_repo_publish"], publish_preview)

    def test_publish_existing_validation_bundle_cannot_override_canonical_intent_or_gate(self):
        temp_root = self.make_temp_root()
        attempt_payload = {
            "artifact_type": ATTEMPT_STATUS_ARTIFACT_TYPE,
            "target_closed_day_utc": "2026-05-10",
            "latest_authoritative_attempt_status": "success",
            "generated_at_utc": "2026-05-11T12:00:00Z",
        }
        success_payload = {
            "artifact_type": SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
            "target_closed_day_utc": "2026-05-10",
            "latest_authoritative_attempt_status": "success",
            "generated_at_utc": "2026-05-11T12:00:00Z",
        }
        run_dir = temp_root / "outputs" / "execution" / "tmp" / "publish_existing_validation" / "case"
        captured_overrides: dict[str, str] = {}

        def fake_build_report_bundle(*, path_overrides, **kwargs):
            captured_overrides.update(path_overrides)
            return {
                "report": {
                    "reference_closed_day_utc": "2026-05-10",
                    "summary": {"block_app": False, "block_execution": False},
                },
                "quality": {"status": "passed"},
            }

        with mock.patch.object(
            pi_producer,
            "build_report_bundle",
            side_effect=fake_build_report_bundle,
        ):
            bundle = pi_producer.build_publish_existing_validation_bundle(
                root=temp_root,
                run_dir=run_dir,
                target_closed_day_utc="2026-05-10",
                attempt_payload=attempt_payload,
                success_payload=success_payload,
            )

        self.assertEqual(bundle["quality"]["status"], "passed")
        self.assertIn("execution_authority_latest_attempt_status", captured_overrides)
        self.assertIn("execution_authority_latest_successful_snapshot", captured_overrides)
        self.assertNotIn("execution_latest_execution_intent", captured_overrides)
        self.assertNotIn("execution_latest_real_order_gate_decision", captured_overrides)
        self.assertFalse(
            (temp_root / "outputs" / "execution" / "intents" / "latest_execution_intent.json").exists()
        )
        self.assertFalse(
            (temp_root / "outputs" / "execution" / "live_gate" / "latest_real_order_gate_decision.json").exists()
        )

    def test_run_publish_existing_flow_live_publish_writes_authority_and_calls_repo_publish(self):
        temp_root = self.make_temp_root()
        attempt_payload, success_payload = self.build_payload_pair()
        authority_state = {
            "run_dir": str(
                temp_root
                / "outputs"
                / "execution"
                / "tmp"
                / "publish_existing_validation"
                / "20260423_111500"
            ),
            "refresh_started_at_utc": "2026-04-23T11:00:00Z",
            "target_closed_day_utc": "2026-04-22",
            "latest_available_closed_utc_day": "2026-04-22",
            "authority_mode": "pi_only_authoritative_producer",
            "pipeline_script_path": "scripts/daily_refresh_app_pipeline.py",
        }
        readiness_bundle = {
            "report": {
                "reference_closed_day_utc": "2026-04-22",
                "summary": {"block_app": False, "block_execution": False},
            },
            "quality": {"status": "passed"},
        }
        repo_publish_result = {
            "published": False,
            "reason": "no_authority_repo_changes",
        }
        command_labels: list[str] = []

        def fake_run_checked_python_command(script_path, *, env, root, args=None, label):
            command_labels.append(label)
            return subprocess.CompletedProcess([sys.executable, str(script_path)], 0)

        publish_authority_success = mock.Mock(return_value={"published": True})

        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "run_checked_python_command",
                    side_effect=fake_run_checked_python_command,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "ensure_required_artifacts_exist",
                    return_value=None,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "determine_publish_existing_target_closed_day",
                    return_value="2026-04-22",
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_authority_state",
                    return_value=dict(authority_state),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "load_publish_existing_app_snapshots",
                    return_value=(
                        self.build_minimal_app_product_snapshot_payload(),
                        self.build_minimal_app_runtime_snapshot_payload(),
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_success_payloads",
                    return_value=(attempt_payload, success_payload, dict(authority_state)),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_publish_existing_validation_bundle",
                    return_value=readiness_bundle,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "validate_publish_existing_readiness_bundle",
                    return_value=readiness_bundle["report"],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "build_report_bundle",
                    return_value=readiness_bundle,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "publish_existing_authority_success_payloads",
                    publish_authority_success,
                )
            )
            publish_repo_mock = stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "publish_authority_artifacts_to_repo",
                    return_value=repo_publish_result,
                )
            )
            result = pi_producer.run_publish_existing_flow(
                root=temp_root,
                env=PI_ENV,
                dry_run=False,
            )

        self.assertEqual(
            command_labels,
            [
                "build_current_strategy_snapshot",
                "validate_current_strategy_snapshot",
                "materialize_execution_app_exports",
                "build_execution_intent_from_strategy_exports",
                "prepare_real_order_gate",
                "materialize_execution_app_exports_from_canonical_execution_chain",
                "build_execution_intent_from_strategy_exports",
                "prepare_real_order_gate",
                "materialize_execution_app_exports_after_authority_sync",
            ],
        )
        self.assertEqual(publish_authority_success.call_count, 2)
        publish_repo_mock.assert_called_once_with(
            root=temp_root,
            env=mock.ANY,
            dry_run=False,
        )
        self.assertEqual(result["authority_artifact_write"], "success_payload_written")
        self.assertEqual(result["authority_repo_publish"], repo_publish_result)

    def test_pi_producer_no_arg_default_uses_publish_existing_dispatch(self):
        flow_result = {
            "mode": "publish-existing",
            "dry_run": False,
            "heavy_refresh_steps": "skipped",
            "authority_repo_publish": {"published": False, "reason": "stub"},
        }
        with mock.patch.object(
            pi_producer,
            "run_publish_existing_flow",
            return_value=flow_result,
        ) as flow_mock, mock.patch.object(
            pi_producer,
            "run_full_refresh_flow",
            side_effect=AssertionError("full-refresh dispatch must stay explicit"),
        ):
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                with self.assertRaises(SystemExit) as exc:
                    pi_producer.main([])

        self.assertEqual(exc.exception.code, 0)
        flow_mock.assert_called_once()
        self.assertIn("[AUTHORITY] mode=publish-existing", stdout.getvalue())
        self.assertIn("[AUTHORITY] heavy_refresh_steps=skipped", stdout.getvalue())

    def test_pi_producer_full_refresh_requires_explicit_mode_for_pipeline(self):
        temp_root = self.make_temp_root()
        script_paths = self.seed_fast_publish_script_placeholders(temp_root)
        publish_mock = mock.Mock(return_value={"published": False, "reason": "stub"})
        subprocess_calls: list[list[str]] = []

        def fake_run(args, cwd=None, env=None, check=None):
            subprocess_calls.append(list(args))
            return subprocess.CompletedProcess(args, 0)

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(pi_producer, "ROOT", temp_root))
            stack.enter_context(
                mock.patch.object(pi_producer, "PIPELINE_SCRIPT", script_paths["pipeline"])
            )
            stack.enter_context(
                mock.patch.object(pi_producer.subprocess, "run", side_effect=fake_run)
            )
            stack.enter_context(
                mock.patch.object(
                    pi_producer,
                    "publish_authority_artifacts_to_repo",
                    publish_mock,
                )
            )
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                with self.assertRaises(SystemExit) as exc:
                    pi_producer.main(
                        [
                            "--mode",
                            "full-refresh",
                            "--skip-legacy-refresh",
                            "--skip-top100-refresh",
                        ]
                    )

        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(
            subprocess_calls,
            [
                [
                    sys.executable,
                    str(script_paths["pipeline"]),
                    "--skip-legacy-refresh",
                    "--skip-top100-refresh",
                ]
            ],
        )
        publish_mock.assert_called_once()
        self.assertIn("[AUTHORITY] mode=full-refresh", stdout.getvalue())
        self.assertIn("[AUTHORITY] heavy_refresh_steps=enabled", stdout.getvalue())

    def test_pi_repo_publish_dry_run_skips_git_commands(self):
        temp_root = self.make_temp_root()
        authority_dir = temp_root / "outputs" / "execution" / "authority"
        authority_dir.mkdir(parents=True, exist_ok=True)
        attempt_path = authority_dir / "latest_attempt_status.json"
        snapshot_path = authority_dir / "latest_successful_snapshot.json"
        self.write_json_file(
            attempt_path,
            {
                "latest_authoritative_attempt_status": "success",
                "automatic_producer_id": "raspberry_pi",
                "authority_role": "pi_only_authoritative_producer",
                "target_closed_day_utc": "2026-04-22",
                "run_id": "20260423_104500",
            },
        )
        self.write_json_file(
            snapshot_path,
            {
                "latest_authoritative_attempt_status": "success",
            },
        )
        env = self.build_pi_repo_env(temp_root)
        with mock.patch.object(
            pi_producer,
            "resolve_authority_publish_paths",
            return_value=[attempt_path.resolve(), snapshot_path.resolve()],
        ), mock.patch.object(
            pi_producer.subprocess,
            "run",
            side_effect=AssertionError("dry-run must not execute git subprocesses"),
        ):
            result = pi_producer.publish_authority_artifacts_to_repo(
                root=temp_root,
                env=env,
                dry_run=True,
            )

        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "dry_run")
        self.assertEqual(result["remote_url"], None)
        self.assertEqual(
            result["pathspecs"],
            [
                "outputs/execution/authority/latest_attempt_status.json",
                "outputs/execution/authority/latest_successful_snapshot.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
