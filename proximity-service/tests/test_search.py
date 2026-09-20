"""End-to-end tests for the read (LBS) and write (Business) service paths."""
import pytest
from app.models import BusinessCreate, BusinessUpdate


@pytest.mark.asyncio
async def test_radius_search_sorted_by_distance(business_svc, lbs_svc):
    await business_svc.create(BusinessCreate(name="A", category="cafe", lat=37.7749, lng=-122.4194, address="x"))
    await business_svc.create(BusinessCreate(name="B", category="cafe", lat=37.7760, lng=-122.4194, address="x"))
    results = await lbs_svc.search_nearby(37.7749, -122.4194, 2000)
    assert len(results) >= 2
    assert results[0].distance_m <= results[1].distance_m


@pytest.mark.asyncio
async def test_radius_excludes_far_business(business_svc, lbs_svc):
    # Golden Gate Park is ~10km from downtown; a 1km query should not find it.
    await business_svc.create(BusinessCreate(name="Far", category="park", lat=37.7694, lng=-122.4862, address="x"))
    results = await lbs_svc.search_nearby(37.7749, -122.4194, 1000)
    assert all(r.business.name != "Far" for r in results)


@pytest.mark.asyncio
async def test_knn_returns_k_results(business_svc, lbs_svc):
    for i in range(20):
        await business_svc.create(BusinessCreate(name=f"Biz{i}", category="x", lat=37.77 + i * 0.001, lng=-122.41, address="x"))
    results = await lbs_svc.search_knn(37.77, -122.41, 5)
    assert len(results) == 5
    assert results[0].distance_m <= results[-1].distance_m


@pytest.mark.asyncio
async def test_geohash_and_quadtree_agree_on_nearest(business_svc, lbs_svc):
    # The single closest business should be identical for both algorithms.
    for i in range(15):
        await business_svc.create(BusinessCreate(name=f"N{i}", category="x", lat=37.77 + i * 0.0008, lng=-122.41, address="x"))
    geo = await lbs_svc.search_nearby(37.77, -122.41, 5000)
    knn = await lbs_svc.search_knn(37.77, -122.41, 1)
    assert geo and knn
    assert geo[0].business.id == knn[0].business.id


@pytest.mark.asyncio
async def test_cache_hit_after_second_query(business_svc, lbs_svc, cache):
    await business_svc.create(BusinessCreate(name="C", category="x", lat=37.7749, lng=-122.4194, address="x"))
    await lbs_svc.search_nearby(37.7749, -122.4194, 5000)
    await lbs_svc.search_nearby(37.7749, -122.4194, 5000)
    assert cache.hits > 0


@pytest.mark.asyncio
async def test_update_coordinates_moves_index(business_svc, lbs_svc):
    bid = await business_svc.create(BusinessCreate(name="Moving", category="cafe", lat=37.7749, lng=-122.4194, address="x"))
    # Relocate it near Golden Gate Bridge, far from the original downtown query.
    await business_svc.update(bid, BusinessUpdate(lat=37.8199, lng=-122.4783))
    downtown = await lbs_svc.search_nearby(37.7749, -122.4194, 1000)
    assert all(r.business.id != bid for r in downtown)
    bridge = await lbs_svc.search_nearby(37.8199, -122.4783, 1000)
    assert any(r.business.id == bid for r in bridge)


@pytest.mark.asyncio
async def test_delete_removes_from_search(business_svc, lbs_svc):
    bid = await business_svc.create(BusinessCreate(name="Doomed", category="cafe", lat=37.7749, lng=-122.4194, address="x"))
    found = await lbs_svc.search_nearby(37.7749, -122.4194, 1000)
    assert any(r.business.id == bid for r in found)
    await business_svc.delete(bid)
    after = await lbs_svc.search_nearby(37.7749, -122.4194, 1000)
    assert all(r.business.id != bid for r in after)
