"""Tests for sync conflict detection and resolution."""
import base64
import pytest


@pytest.mark.asyncio
async def test_sync_client_behind_gets_update(svc):
    """Client at v1, server at v2 → sync returns update."""
    data1 = b"version1!!"  # 10 bytes = 1 block (block_size=10)
    h1, b1 = svc._block_server.split(data1)
    sid, fid, _ = await svc.start_upload("u_test", "doc", "/doc", len(data1), len(h1))
    await svc.upload_blocks(sid, [{"hash": h1[0], "data_b64": base64.b64encode(b1[0]).decode()}])
    await svc.commit("u_test", sid, fid, h1)

    # Server goes to v2
    data2 = b"version2!!"
    h2, b2 = svc._block_server.split(data2)
    sid2, _, _ = await svc.start_upload("u_test", "doc", "/doc", len(data2), len(h2), file_id=fid)
    await svc.upload_blocks(sid2, [{"hash": h2[0], "data_b64": base64.b64encode(b2[0]).decode()}])
    await svc.commit("u_test", sid2, fid, h2)

    # Client syncs from v1
    result = await svc.sync("u_test", [{"file_id": fid, "base_version": 1, "block_hashes": []}])
    assert len(result["updates"]) == 1
    assert result["updates"][0]["server_version"] == 2
    assert result["updates"][0]["block_hashes"] == h2


@pytest.mark.asyncio
async def test_conflict_detected(svc):
    """Two edits from same base → second gets conflict."""
    original = b"original!!"
    h_orig, b_orig = svc._block_server.split(original)
    sid0, fid, _ = await svc.start_upload("u_test", "doc", "/doc", len(original), len(h_orig))
    await svc.upload_blocks(sid0, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(h_orig, b_orig)])
    v1 = await svc.commit("u_test", sid0, fid, h_orig)

    # Edit A
    edit_a = b"edit_a!!!!"
    hA, bA = svc._block_server.split(edit_a)
    sidA, _, _ = await svc.start_upload("u_test", "doc", "/doc", len(edit_a), len(hA), file_id=fid)
    await svc.upload_blocks(sidA, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hA, bA)])
    vA = await svc.commit("u_test", sidA, fid, hA)

    # Edit B (also from base v1) → sync detects conflict
    edit_b = b"edit_b!!!!"
    hB, bB = svc._block_server.split(edit_b)
    sidB, _, _ = await svc.start_upload("u_test", "doc", "/doc", len(edit_b), len(hB), file_id=fid)
    await svc.upload_blocks(sidB, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hB, bB)])

    # Sync: client B has base_version=1 but server is v2 (from edit A)
    result = await svc.sync("u_test", [{"file_id": fid, "base_version": v1, "block_hashes": hB}])
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["client_base_version"] == v1
    assert result["conflicts"][0]["server_version"] == vA

    # Both copies exist in storage
    assert svc._object_store.exists(hA[0])
    assert svc._object_store.exists(hB[0])


@pytest.mark.asyncio
async def test_resolve_override(svc):
    """After conflict, override promotes loser to new version."""
    original = b"original!!"
    h_orig, b_orig = svc._block_server.split(original)
    sid0, fid, _ = await svc.start_upload("u_test", "doc", "/doc", len(original), len(h_orig))
    await svc.upload_blocks(sid0, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(h_orig, b_orig)])
    await svc.commit("u_test", sid0, fid, h_orig)

    # v2 by another edit
    edit_a = b"edit_a!!!!"
    hA, bA = svc._block_server.split(edit_a)
    sidA, _, _ = await svc.start_upload("u_test", "doc", "/doc", len(edit_a), len(hA), file_id=fid)
    await svc.upload_blocks(sidA, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hA, bA)])
    await svc.commit("u_test", sidA, fid, hA)

    # Resolve: override with client's blocks
    edit_b = b"edit_b!!!!"
    hB, bB = svc._block_server.split(edit_b)
    # Store blocks B in object store first (simulating they were uploaded)
    for h, b in zip(hB, bB):
        svc._object_store.put_if_absent(h, b)

    new_v = await svc.resolve("u_test", fid, "override", hB)
    assert new_v == 3

    # Download should return edit_b content
    downloaded = await svc.download("u_test", fid)
    assert downloaded == edit_b


@pytest.mark.asyncio
async def test_resolve_keep(svc):
    """After conflict, keep returns server version (no data change)."""
    data = b"server_ver"
    h, b = svc._block_server.split(data)
    sid, fid, _ = await svc.start_upload("u_test", "doc", "/doc", len(data), len(h))
    await svc.upload_blocks(sid, [{"hash": h[0], "data_b64": base64.b64encode(b[0]).decode()}])
    v = await svc.commit("u_test", sid, fid, h)

    kept_v = await svc.resolve("u_test", fid, "keep")
    assert kept_v == v
