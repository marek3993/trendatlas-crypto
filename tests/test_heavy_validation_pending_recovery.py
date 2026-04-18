import json
import unittest
from types import SimpleNamespace
from unittest import mock

from services.pc import worker_service
from services.pi import job_queue
from services.shared.schemas import JOB_STATUS_SUCCEEDED


class RedisStreamQueuePendingRecoveryTest(unittest.TestCase):
    def test_consume_prioritizes_own_pending_then_stale_claim_then_fresh(self) -> None:
        stream = "research_os:heavy_validation_jobs"
        group = "research_os_pc_workers"
        consumer = "pc_worker_01_heavy_validation"
        queue = object.__new__(job_queue.RedisStreamQueue)
        queue._client = mock.Mock()
        queue._ensure_group = mock.Mock()
        queue._client.xreadgroup.side_effect = [
            [(stream, [("1-0", {"payload": json.dumps({"source": "own_pending"})})])],
            [(stream, [("3-0", {"payload": json.dumps({"source": "fresh"})})])],
        ]
        queue._client.xautoclaim.return_value = (
            "0-0",
            [("2-0", {"payload": json.dumps({"source": "stale_claim"})})],
            [],
        )

        messages = queue.consume(
            stream=stream,
            group=group,
            consumer=consumer,
            count=3,
            block_ms=250,
            include_pending=True,
            stale_claim_idle_ms=worker_service.HEAVY_VALIDATION_STALE_CLAIM_IDLE_MS,
        )

        self.assertEqual([message.message_id for message in messages], ["1-0", "2-0", "3-0"])
        self.assertEqual(
            [message.payload["source"] for message in messages],
            ["own_pending", "stale_claim", "fresh"],
        )
        queue._client.xreadgroup.assert_has_calls(
            [
                mock.call(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: "0"},
                    count=3,
                ),
                mock.call(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: ">"},
                    count=1,
                    block=250,
                ),
            ]
        )
        queue._client.xautoclaim.assert_called_once_with(
            name=stream,
            groupname=group,
            consumername=consumer,
            min_idle_time=worker_service.HEAVY_VALIDATION_STALE_CLAIM_IDLE_MS,
            start_id="0-0",
            count=2,
        )


class HeavyValidationConsumeOnceTest(unittest.TestCase):
    def test_consume_heavy_validation_once_enables_pending_recovery_and_acks_success(self) -> None:
        config = SimpleNamespace(
            role="pc_worker",
            queue_backend="redis_streams",
            redis_url="redis://127.0.0.1:6379/0",
            registry_path="outputs/research_os/dev_only/mvp/registry/research_os_mvp.sqlite",
            artifact_root="outputs/research_os/dev_only/mvp/artifacts",
            consumer_group="research_os_pc_workers",
            consumer_name="pc_worker_01",
            streams={"heavy_validation_jobs": "research_os:heavy_validation_jobs"},
        )
        queue = mock.Mock()
        message = job_queue.QueueMessage(
            stream="research_os:heavy_validation_jobs",
            message_id="1-0",
            payload={"request_artifact_path": "C:/tmp/request.json"},
        )
        result = mock.Mock(status=JOB_STATUS_SUCCEEDED)

        with (
            mock.patch.object(worker_service, "load_runtime_config", return_value=config),
            mock.patch.object(worker_service, "assert_runtime_startup_ready"),
            mock.patch.object(worker_service, "RegistryService"),
            mock.patch.object(worker_service, "consume_exactly_one", return_value=message) as consume_mock,
            mock.patch.object(worker_service, "execute_heavy_validation_message", return_value=result),
        ):
            results = worker_service.consume_heavy_validation_once("config.json", queue=queue)

        self.assertEqual(results, [result])
        consume_mock.assert_called_once_with(
            queue=queue,
            stream="research_os:heavy_validation_jobs",
            group="research_os_pc_workers",
            consumer="pc_worker_01_heavy_validation",
            include_pending=True,
            stale_claim_idle_ms=worker_service.HEAVY_VALIDATION_STALE_CLAIM_IDLE_MS,
        )
        queue.ack.assert_called_once_with(
            "research_os:heavy_validation_jobs",
            "research_os_pc_workers",
            "1-0",
        )


if __name__ == "__main__":
    unittest.main()
