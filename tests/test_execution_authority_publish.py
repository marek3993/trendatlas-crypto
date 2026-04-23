import argparse
import json
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
    def make_temp_root(self) -> Path:
        base_dir = ROOT / "outputs" / "_tmp_test_execution_authority_publish"
        base_dir.mkdir(parents=True, exist_ok=True)
        temp_root = base_dir / f"case_{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, temp_root, True)
        return temp_root

    def seed_app_snapshots(self, temp_root: Path) -> None:
        app_snapshot_dir = temp_root / "outputs" / "execution" / "app_snapshot"
        app_snapshot_dir.mkdir(parents=True, exist_ok=True)
        (app_snapshot_dir / "app_product_snapshot.json").write_text(
            json.dumps(
                {
                    "freshness_target_closed_day": "2026-04-22",
                    "strategy_last_closed_day": "2026-04-22",
                }
            ),
            encoding="utf-8",
        )
        (app_snapshot_dir / "app_runtime_snapshot.json").write_text(
            json.dumps(
                {
                    "latest_available_closed_utc_date": "2026-04-22",
                    "latest_strategy_artifact_date": "2026-04-22",
                }
            ),
            encoding="utf-8",
        )

    def patch_helper_paths(self, stack: ExitStack, temp_root: Path) -> None:
        pipeline_script = temp_root / "scripts" / "daily_refresh_app_pipeline.py"
        pipeline_script.parent.mkdir(parents=True, exist_ok=True)
        pipeline_script.write_text("# helper test placeholder\n", encoding="utf-8")
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
            "verify_outputs",
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
        self.assertEqual(
            result["pathspecs"],
            [
                "outputs/execution/authority/latest_attempt_status.json",
                "outputs/execution/authority/latest_successful_snapshot.json",
            ],
        )
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
                [
                    "git",
                    "add",
                    "--",
                    "outputs/execution/authority/latest_attempt_status.json",
                    "outputs/execution/authority/latest_successful_snapshot.json",
                ],
                [
                    "git",
                    "diff",
                    "--cached",
                    "--quiet",
                    "--",
                    "outputs/execution/authority/latest_attempt_status.json",
                    "outputs/execution/authority/latest_successful_snapshot.json",
                ],
                [
                    "git",
                    "commit",
                    "--only",
                    "-m",
                    "Publish Pi authority artifacts: success 2026-04-22 20260423_104500",
                    "--",
                    "outputs/execution/authority/latest_attempt_status.json",
                    "outputs/execution/authority/latest_successful_snapshot.json",
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


if __name__ == "__main__":
    unittest.main()
