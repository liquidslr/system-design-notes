"""
FastAPI server for the Search Autocomplete System.

Provides REST API endpoints for:
- Getting autocomplete suggestions
- Recording user queries
- Managing the suggestion filter
- Triggering trie rebuilds
- Viewing system statistics
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import database as db
from app.config import config
from app.trie import Trie
from app.filter import SuggestionFilter
from app.query_service import QueryService
from app.aggregator import Aggregator
from app.models import (
    SuggestionsResponse,
    SuggestionResponse,
    QueryRequest,
    QueryResponse,
    FilterRequest,
    FilterResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
trie: Trie | None = None
query_service: QueryService | None = None
aggregator: Aggregator | None = None
suggestion_filter: SuggestionFilter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and clean up on shutdown."""
    global trie, query_service, aggregator, suggestion_filter

    # 1. Initialize database
    await db.init_db()

    # 2. Initialize trie and filter
    trie = Trie()
    suggestion_filter = SuggestionFilter()
    await suggestion_filter.load()

    # 3. Build initial trie from seed data + database frequencies
    all_freqs = await db.get_all_frequencies()
    if all_freqs:
        # Use database frequencies if available
        clean_freqs = {
            q: f for q, f in all_freqs.items()
            if not suggestion_filter.is_blocked(q)
        }
        trie.build_from_frequencies(clean_freqs)
        logger.info(f"Trie built from DB: {len(clean_freqs)} queries")
    else:
        # First run: seed with demo data
        seed = {
            q: f for q, f in config.seed_queries.items()
            if not suggestion_filter.is_blocked(q)
        }
        trie.build_from_frequencies(seed)
        await db.aggregate_frequencies(config.seed_queries)
        logger.info(f"Trie seeded with {len(seed)} demo queries")

    # 4. Create query service
    query_service = QueryService(trie, suggestion_filter)

    # 5. Start aggregator
    aggregator = Aggregator(trie, suggestion_filter)
    await aggregator.start()

    logger.info("Search Autocomplete System started")
    yield

    # Shutdown
    await aggregator.stop()
    logger.info("Search Autocomplete System stopped")


app = FastAPI(
    title="Search Autocomplete System",
    description="Real-time search suggestions powered by a Trie with top-k caching",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(prefix: str):
    """Get autocomplete suggestions for a prefix."""
    if not prefix or not prefix.strip():
        return SuggestionsResponse(prefix="", suggestions=[])

    suggestions = query_service.get_suggestions(prefix)
    return SuggestionsResponse(
        prefix=prefix.lower().strip(),
        suggestions=[SuggestionResponse(**s) for s in suggestions],
    )


@app.post("/api/queries", response_model=QueryResponse)
async def record_query(request: QueryRequest):
    """Record a user search query for future aggregation."""
    query = request.query.lower().strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    await db.log_query(query)
    return QueryResponse(status="logged", query=query)


@app.post("/api/filter", response_model=FilterResponse)
async def add_filter(request: FilterRequest):
    """Add a query to the filter blocklist."""
    await suggestion_filter.add(request.query, request.reason)

    # Remove from trie immediately
    trie.delete(request.query)
    trie.rebuild_caches()

    return FilterResponse(status="filtered", query=request.query)


@app.delete("/api/filter/{query}", response_model=FilterResponse)
async def remove_filter(query: str):
    """Remove a query from the filter blocklist."""
    removed = await suggestion_filter.remove(query)
    if not removed:
        raise HTTPException(status_code=404, detail="Query not in filter list")

    # Rebuild trie to include the unfiltered query
    all_freqs = await db.get_all_frequencies()
    clean_freqs = {
        q: f for q, f in all_freqs.items()
        if not suggestion_filter.is_blocked(q)
    }
    trie.build_from_frequencies(clean_freqs)

    return FilterResponse(status="unfiltered", query=query)


@app.post("/api/trie/rebuild")
async def rebuild_trie():
    """Manually trigger trie rebuild from latest aggregated data."""
    stats = await aggregator.rebuild_now()
    return {"status": "rebuilt", "stats": stats}


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get system statistics."""
    trie_stats = trie.get_all_stats()
    log_count = await db.get_total_log_count()
    filter_count = await db.get_filter_count()

    return StatsResponse(
        trie_nodes=trie_stats["trie_nodes"],
        total_queries=trie_stats["total_queries"],
        total_frequency=trie_stats["total_frequency"],
        filtered_queries=filter_count,
        aggregation_count=log_count,
    )
