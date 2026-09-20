"""Pydantic request/response models for the Proximity Service."""
from __future__ import annotations
from pydantic import BaseModel, field_validator


class BusinessCreate(BaseModel):
    name: str
    category: str = "general"
    lat: float
    lng: float
    address: str = ""

    @field_validator("lat")
    @classmethod
    def _check_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("lat must be in [-90, 90]")
        return v

    @field_validator("lng")
    @classmethod
    def _check_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("lng must be in [-180, 180]")
        return v


class BusinessUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    lat: float | None = None
    lng: float | None = None
    address: str | None = None


class Business(BaseModel):
    id: int
    name: str
    category: str
    lat: float
    lng: float
    address: str
    created_at: str


class SearchResult(BaseModel):
    business: Business
    distance_m: float


class NearbyResponse(BaseModel):
    lat: float
    lng: float
    radius_m: float
    items: list[SearchResult]


class KnnResponse(BaseModel):
    lat: float
    lng: float
    k: int
    items: list[SearchResult]


class AlgorithmResult(BaseModel):
    items: list[SearchResult]
    ms: float


class CompareResponse(BaseModel):
    geohash: AlgorithmResult
    quadtree: AlgorithmResult


class StatsResponse(BaseModel):
    businesses: int
    grids: int
    quadtree_points: int
    cache_hits: int
    cache_misses: int
