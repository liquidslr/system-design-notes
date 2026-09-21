"""Tests for notification center: publish, poll, long-poll wake, offline queue."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_publish_and_consume(svc):
    """Publish event then poll returns it."""
    await svc._notifier.publish("u_test", "file1", "add", {"name": "test.txt"})
    events = await svc._notifier.poll("u_test", since_id=0, wait=0.1)
    assert len(events) >= 1
    assert events[0]["file_id"] == "file1"
    assert events[0]["event"] == "add"


@pytest.mark.asyncio
async def test_poll_returns_empty_on_timeout(svc):
    """No events → poll returns empty after timeout."""
    events = await svc._notifier.poll("u_test", since_id=999, wait=0.2)
    assert events == []


@pytest.mark.asyncio
async def test_long_poll_wakes_on_publish(svc):
    """Publishing while poll is waiting wakes the poller immediately."""
    async def delayed_publish():
        await asyncio.sleep(0.1)
        await svc._notifier.publish("u_test", "file2", "edit", {"v": 2})

    task = asyncio.create_task(delayed_publish())
    events = await svc._notifier.poll("u_test", since_id=0, wait=3.0)
    assert len(events) == 1
    assert events[0]["file_id"] == "file2"
    task.cancel()


@pytest.mark.asyncio
async def test_offline_client_pulls_backlog(svc):
    """Events accumulate; offline client pulls all with since_id=0."""
    await svc._notifier.publish("u_test", "f1", "add", {})
    await svc._notifier.poll("u_test", since_id=0, wait=0.1)  # marks delivered

    await svc._notifier.publish("u_test", "f2", "edit", {})
    await svc._notifier.publish("u_test", "f3", "delete", {})

    # New "session" with since_id=0 won't see already-delivered f1
    # but will see undelivered f2 and f3
    events = await svc._notifier.poll("u_test", since_id=0, wait=0.1)
    file_ids = [e["file_id"] for e in events]
    assert "f2" in file_ids
    assert "f3" in file_ids


@pytest.mark.asyncio
async def test_commit_triggers_notification(svc):
    """Uploading and committing a file triggers 'add' notification to owner."""
    import base64
    data = b"notify_me"
    hashes, blocks = svc._block_server.split(data)
    sid, fid, _ = await svc.start_upload("u_test", "n.bin", "/n.bin", len(data), len(hashes))
    await svc.upload_blocks(sid, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hashes, blocks)])
    await svc.commit("u_test", sid, fid, hashes)

    events = await svc._notifier.poll("u_test", since_id=0, wait=0.1)
    assert any(e["event"] == "add" for e in events)
