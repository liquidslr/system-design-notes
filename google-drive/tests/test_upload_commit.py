"""Tests for upload, commit, dedup, download, and quota."""
import base64
import pytest
from app.api_service import QuotaExceededError


@pytest.mark.asyncio
async def test_full_upload_and_download(svc):
    """Upload 25 bytes with block_size=10 → 3 blocks → download and verify."""
    data = b"x" * 10 + b"y" * 10 + b"z" * 5
    hashes, blocks = svc._block_server.split(data)
    assert len(hashes) == 3

    sid, fid, dedup = await svc.start_upload("u_test", "test.bin", "/test.bin", len(data), len(hashes), block_hashes=hashes)
    assert len(dedup) == 0  # first upload, nothing known

    payloads = [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hashes, blocks)]
    received = await svc.upload_blocks(sid, payloads)
    assert len(received) == 3

    v = await svc.commit("u_test", sid, fid, hashes)
    assert v == 1

    downloaded = await svc.download("u_test", fid)
    assert downloaded == data


@pytest.mark.asyncio
async def test_dedup_across_files(svc):
    """Second file with same blocks → 0 new physical storage."""
    data = b"shared_content!"  # 15 bytes, block_size=10 → 2 blocks
    hashes, blocks = svc._block_server.split(data)

    # First upload
    sid1, fid1, _ = await svc.start_upload("u_test", "f1", "/f1", len(data), len(hashes))
    await svc.upload_blocks(sid1, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hashes, blocks)])
    await svc.commit("u_test", sid1, fid1, hashes)

    # Second upload — identical content → dedup at start_upload
    sid2, fid2, dedup = await svc.start_upload("u_test", "f2", "/f2", len(data), len(hashes), block_hashes=hashes)
    assert len(dedup) == 2  # all hashes already known
    # No need to upload blocks — commit directly
    v2 = await svc.commit("u_test", sid2, fid2, hashes)
    assert v2 == 1

    # Verify ref_count incremented
    blk = await svc._db.get_block(hashes[0])
    assert blk["ref_count"] == 2


@pytest.mark.asyncio
async def test_resumable_upload(svc):
    """Simulate interrupted upload → query status → resume."""
    data = b"a" * 10 + b"b" * 10 + b"c" * 10
    hashes, blocks = svc._block_server.split(data)

    sid, fid, _ = await svc.start_upload("u_test", "resume.bin", "/resume.bin", len(data), len(hashes))

    # Upload only first 2 blocks (simulating interruption)
    await svc.upload_blocks(sid, [{"hash": hashes[0], "data_b64": base64.b64encode(blocks[0]).decode()},
                                   {"hash": hashes[1], "data_b64": base64.b64encode(blocks[1]).decode()}])

    status = await svc.get_session_status(sid)
    assert len(status["received_hashes"]) == 2
    assert status["missing_count"] == 1

    # Resume: upload the missing block
    await svc.upload_blocks(sid, [{"hash": hashes[2], "data_b64": base64.b64encode(blocks[2]).decode()}])
    status = await svc.get_session_status(sid)
    assert status["missing_count"] == 0

    v = await svc.commit("u_test", sid, fid, hashes)
    assert v == 1


@pytest.mark.asyncio
async def test_delta_sync_one_block_changed(svc):
    """Edit 1 block of a 3-block file -> only changed block uploaded."""
    # block_size=10, so each segment fills exactly one block
    original = b"A" * 10 + b"B" * 10 + b"C" * 4  # 3 blocks: AAAA, BBBB, CC
    h1, b1 = svc._block_server.split(original)
    sid, fid, _ = await svc.start_upload("u_test", "delta.bin", "/delta.bin", len(original), len(h1))
    await svc.upload_blocks(sid, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(h1, b1)])
    await svc.commit("u_test", sid, fid, h1)

    # Edit: change only the middle block (block 0 and 2 stay identical)
    modified = b"A" * 10 + b"Z" * 10 + b"C" * 4
    h2, b2 = svc._block_server.split(modified)
    # Block 0 same, block 1 different, block 2 same -> only 1 missing
    missing = svc._block_server.which_hashes_missing(h2)
    assert len(missing) == 1  # only block index 1 is new

    sid2, _, _ = await svc.start_upload("u_test", "delta.bin", "/delta.bin", len(modified), len(h2), file_id=fid)
    await svc.upload_blocks(sid2, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(h2, b2) if h in set(missing)])
    v2 = await svc.commit("u_test", sid2, fid, h2)
    assert v2 == 2

    downloaded = await svc.download("u_test", fid)
    assert downloaded == modified


@pytest.mark.asyncio
async def test_quota_exceeded(svc):
    """Upload beyond quota → QuotaExceededError."""
    # User has 1MB quota. Upload a "large" file that exceeds it.
    # Patch quota to be tiny
    await svc._db.execute("UPDATE users SET quota_bytes=15 WHERE user_id='u_test'")
    data = b"x" * 25  # 25 bytes > 15 quota
    hashes, blocks = svc._block_server.split(data)
    sid, fid, _ = await svc.start_upload("u_test", "big.bin", "/big.bin", len(data), len(hashes))
    await svc.upload_blocks(sid, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hashes, blocks)])
    with pytest.raises(QuotaExceededError):
        await svc.commit("u_test", sid, fid, hashes)
