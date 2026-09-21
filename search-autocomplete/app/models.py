"""
Pydantic models for request/response validation.
"""
from pydantic import BaseModel, Field


class SuggestionResponse(BaseModel):
    """A single autocomplete suggestion."""
    query: str
    frequency: int


class SuggestionsResponse(BaseModel):
    """Response for GET /api/suggestions."""
    prefix: str
    suggestions: list[SuggestionResponse]


class QueryRequest(BaseModel):
    """Request body for POST /api/queries."""
    query: str = Field(..., min_length=1, max_length=200)


class QueryResponse(BaseModel):
    """Response for POST /api/queries."""
    status: str
    query: str


class FilterRequest(BaseModel):
    """Request body for POST /api/filter."""
    query: str = Field(..., min_length=1)
    reason: str = "inappropriate"


class FilterResponse(BaseModel):
    """Response for filter operations."""
    status: str
    query: str


class StatsResponse(BaseModel):
    """Response for GET /api/stats."""
    trie_nodes: int
    total_queries: int
    total_frequency: int
    filtered_queries: int
    aggregation_count: int
