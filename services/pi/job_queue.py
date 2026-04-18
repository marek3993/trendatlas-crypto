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

    def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block_ms: int = 1000,
        include_pending: bool = False,
        stale_claim_idle_ms: int | None = None,
    ) -> list[QueueMessage]:
        raise NotImplementedError

    def ack(self, stream: str, group: str, message_id: str) -> None:
        raise NotImplementedError

    def ping(self) -> bool:
        raise NotImplementedError

    def prepare_consumer_group(self, stream: str, group: str) -> None:
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
    include_pending: bool = False,
    stale_claim_idle_ms: int | None = None,
) -> QueueMessage | None:
    messages = queue.consume(
        stream=stream,
        group=group,
        consumer=consumer,
        count=1,
        block_ms=block_ms,
        include_pending=include_pending,
        stale_claim_idle_ms=stale_claim_idle_ms,
    )
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

    def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block_ms: int = 1000,
        include_pending: bool = False,
        stale_claim_idle_ms: int | None = None,
    ) -> list[QueueMessage]:
        del block_ms, include_pending, stale_claim_idle_ms
        key = (stream, group, consumer)
        offset = self._offsets.get(key, 0)
        messages = self._streams.get(stream, [])
        batch = messages[offset : offset + count]
        self._offsets[key] = offset + len(batch)
        return list(batch)

    def ack(self, stream: str, group: str, message_id: str) -> None:
        del stream, group, message_id

    def ping(self) -> bool:
        return True

    def prepare_consumer_group(self, stream: str, group: str) -> None:
        del group
        self._streams.setdefault(stream, [])


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

    def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block_ms: int = 1000,
        include_pending: bool = False,
        stale_claim_idle_ms: int | None = None,
    ) -> list[QueueMessage]:
        self._ensure_group(stream=stream, group=group)
        messages: list[QueueMessage] = []
        seen_ids: set[str] = set()

        def extend_unique(batch: list[QueueMessage]) -> None:
            for message in batch:
                if message.message_id in seen_ids:
                    continue
                seen_ids.add(message.message_id)
                messages.append(message)
                if len(messages) >= count:
                    break

        if include_pending:
            own_pending = self._read_group_entries(
                stream=stream,
                group=group,
                consumer=consumer,
                stream_cursor="0",
                count=count,
            )
            extend_unique(own_pending)
            if stale_claim_idle_ms is not None and len(messages) < count:
                stale_pending = self._claim_stale_pending(
                    stream=stream,
                    group=group,
                    consumer=consumer,
                    count=count - len(messages),
                    min_idle_time_ms=stale_claim_idle_ms,
                )
                extend_unique(stale_pending)
        if len(messages) < count:
            fresh_messages = self._read_group_entries(
                stream=stream,
                group=group,
                consumer=consumer,
                stream_cursor=">",
                count=count - len(messages),
                block_ms=block_ms,
            )
            extend_unique(fresh_messages)
        return messages

    def ack(self, stream: str, group: str, message_id: str) -> None:
        self._client.xack(stream, group, message_id)

    def ping(self) -> bool:
        return bool(self._client.ping())

    def prepare_consumer_group(self, stream: str, group: str) -> None:
        self._ensure_group(stream=stream, group=group)

    def _ensure_group(self, stream: str, group: str) -> None:
        try:
            self._client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def _read_group_entries(
        self,
        stream: str,
        group: str,
        consumer: str,
        stream_cursor: str,
        count: int,
        block_ms: int | None = None,
    ) -> list[QueueMessage]:
        kwargs: dict[str, Any] = {
            "groupname": group,
            "consumername": consumer,
            "streams": {stream: stream_cursor},
            "count": count,
        }
        if block_ms is not None:
            kwargs["block"] = block_ms
        raw_entries = self._client.xreadgroup(**kwargs)
        return self._parse_stream_entries(raw_entries)

    def _claim_stale_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int,
        min_idle_time_ms: int,
    ) -> list[QueueMessage]:
        claimed: list[QueueMessage] = []
        cursor = "0-0"
        seen_cursors: set[str] = set()
        while len(claimed) < count:
            raw_claim = self._client.xautoclaim(
                name=stream,
                groupname=group,
                consumername=consumer,
                min_idle_time=min_idle_time_ms,
                start_id=cursor,
                count=count - len(claimed),
            )
            next_cursor, batch = self._parse_xautoclaim_entries(stream=stream, raw_claim=raw_claim)
            claimed.extend(batch)
            cursor = next_cursor or "0-0"
            if cursor in {"0", "0-0"} or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        return claimed

    def _parse_stream_entries(self, raw_entries: list[tuple[str, list[tuple[str, dict[str, str]]]]]) -> list[QueueMessage]:
        messages: list[QueueMessage] = []
        for raw_stream, entries in raw_entries:
            for message_id, fields in entries:
                messages.append(self._build_message(stream=str(raw_stream), message_id=message_id, fields=fields))
        return messages

    def _parse_xautoclaim_entries(self, stream: str, raw_claim: Any) -> tuple[str, list[QueueMessage]]:
        if not raw_claim:
            return "0-0", []
        next_cursor = str(raw_claim[0])
        entries = raw_claim[1] if len(raw_claim) > 1 else []
        messages = [
            self._build_message(stream=stream, message_id=message_id, fields=fields)
            for message_id, fields in entries
        ]
        return next_cursor, messages

    def _build_message(self, stream: str, message_id: str, fields: dict[str, str]) -> QueueMessage:
        payload = json.loads(fields.get("payload", "{}"))
        return QueueMessage(stream=stream, message_id=str(message_id), payload=payload)


def build_queue(backend: str, redis_url: str) -> JobQueue:
    normalized = backend.strip().lower().replace("-", "_")
    if normalized == "memory":
        return InMemoryStreamQueue()
    if normalized in {"redis", "redis_streams"}:
        return RedisStreamQueue(redis_url=redis_url)
    raise ValueError(f"unsupported queue backend: {backend}")
