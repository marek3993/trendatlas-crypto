from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class QueueMessage:
    stream: str
    message_id: str
    payload: dict[str, Any]


class JobQueue(Protocol):
    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def consume(self, stream: str, group: str, consumer: str, count: int = 1, block_ms: int = 1000) -> list[QueueMessage]:
        raise NotImplementedError

    def ack(self, stream: str, group: str, message_id: str) -> None:
        raise NotImplementedError


def publish_exactly_one(queue: JobQueue, stream: str, payload: dict[str, Any]) -> dict[str, Any]:
    message_id = queue.publish(stream=stream, payload=payload)
    return {
        "published_count": 1,
        "stream": stream,
        "message_id": message_id,
    }


def consume_exactly_one(
    queue: JobQueue,
    stream: str,
    group: str,
    consumer: str,
    block_ms: int = 1000,
) -> QueueMessage | None:
    messages = queue.consume(stream=stream, group=group, consumer=consumer, count=1, block_ms=block_ms)
    if len(messages) > 1:
        raise RuntimeError(f"queue returned more than one message from {stream}: {len(messages)}")
    return messages[0] if messages else None


class InMemoryStreamQueue:
    """Small local queue for smoke tests; production should use RedisStreamQueue."""

    def __init__(self) -> None:
        self._streams: dict[str, list[QueueMessage]] = {}
        self._offsets: dict[tuple[str, str, str], int] = {}

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        messages = self._streams.setdefault(stream, [])
        message_id = f"{len(messages) + 1}-0"
        messages.append(QueueMessage(stream=stream, message_id=message_id, payload=dict(payload)))
        return message_id

    def consume(self, stream: str, group: str, consumer: str, count: int = 1, block_ms: int = 1000) -> list[QueueMessage]:
        del block_ms
        key = (stream, group, consumer)
        offset = self._offsets.get(key, 0)
        messages = self._streams.get(stream, [])
        batch = messages[offset : offset + count]
        self._offsets[key] = offset + len(batch)
        return list(batch)

    def ack(self, stream: str, group: str, message_id: str) -> None:
        del stream, group, message_id


class RedisStreamQueue:
    """Redis Streams adapter used by the Pi orchestrator and PC worker."""

    def __init__(self, redis_url: str) -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis queue backend requires the optional 'redis' Python package.") from exc
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        return str(self._client.xadd(stream, {"payload": json.dumps(payload, sort_keys=True, default=str)}))

    def consume(self, stream: str, group: str, consumer: str, count: int = 1, block_ms: int = 1000) -> list[QueueMessage]:
        self._ensure_group(stream=stream, group=group)
        raw_entries = self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
        messages: list[QueueMessage] = []
        for raw_stream, entries in raw_entries:
            for message_id, fields in entries:
                payload = json.loads(fields.get("payload", "{}"))
                messages.append(QueueMessage(stream=str(raw_stream), message_id=str(message_id), payload=payload))
        return messages

    def ack(self, stream: str, group: str, message_id: str) -> None:
        self._client.xack(stream, group, message_id)

    def _ensure_group(self, stream: str, group: str) -> None:
        try:
            self._client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise


def build_queue(backend: str, redis_url: str) -> JobQueue:
    normalized = backend.strip().lower().replace("-", "_")
    if normalized == "memory":
        return InMemoryStreamQueue()
    if normalized in {"redis", "redis_streams"}:
        return RedisStreamQueue(redis_url=redis_url)
    raise ValueError(f"unsupported queue backend: {backend}")
