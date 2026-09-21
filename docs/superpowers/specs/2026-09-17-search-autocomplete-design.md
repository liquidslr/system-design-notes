# Search Autocomplete System - Implementation Spec

## Goal
Implement a search autocomplete system based on the design in Chapter 13, featuring a Trie data structure with top-k caching, a data gathering pipeline, and a Vue 3 frontend with real-time suggestions.

## Architecture

### Directory Structure
```
search-autocomplete/
├── app/
│   ├── __init__.py
│   ├── config.py          # Configuration constants
│   ├── models.py          # Pydantic request/response models
│   ├── database.py        # aiosqlite async database layer
│   ├── trie.py            # Trie data structure with top-k caching
│   ├── query_service.py   # Query processing and suggestion retrieval
│   ├── aggregator.py      # Background data aggregation worker
│   ├── filter.py          # Suggestion filter (blocklist)
│   └── server.py          # FastAPI server + REST API
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── components/SearchBox.vue
│   │   └── main.js
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   └── Dockerfile
├── __main__.py            # CLI entry point
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/suggestions` | GET | Get autocomplete suggestions (`?prefix=tw`) |
| `/api/queries` | POST | Record a user search query |
| `/api/trie/rebuild` | POST | Manually trigger trie rebuild |
| `/api/stats` | GET | System statistics (node count, total queries, etc.) |

## Core Components

### Trie Data Structure (`trie.py`)

**TrieNode:**
- `children: dict[str, TrieNode]` — up to 26 lowercase English letters
- `frequency: int` — number of times this exact query was searched
- `top_k: list[tuple[str, int]]` — cached top-5 suggestions (query, freq)
- `is_end: bool` — marks end of a complete query

**Operations:**
1. `insert(query, freq)` — Insert/update query, update top-k caches along the path
2. `search_prefix(prefix) -> list[tuple[str, int]]` — Find prefix node, return its cached top-k (O(1) after prefix traversal)
3. `delete(query)` — Remove query from trie (for filtered suggestions)
4. `build_from_frequencies(freq_dict)` — Batch build trie from frequency dictionary
5. `rebuild()` — Load latest aggregated data from DB, rebuild entire trie

**Top-k Cache Maintenance:** After each insert, traverse from the node upward, maintaining a min-heap of size 5 at each node. Queries return cached data directly without subtree traversal.

**Constraints:**
- Maximum prefix length: 50 characters (truncate longer queries)
- Only lowercase English characters (a-z)
- Top-k size: 5 suggestions

### Query Service (`query_service.py`)

Handles the query processing flow:
1. Receive prefix from user input
2. Validate prefix (length, character set)
3. Check filter list for blocked terms
4. Look up prefix in trie, return cached top-k suggestions
5. If prefix not found, return empty list

### Data Gathering Pipeline

**Database Tables:**
- `query_logs` — Raw query records (id, query, timestamp)
- `frequencies` — Aggregated frequencies (query, count, last_updated)
- `filter_list` — Blocked queries (query, reason, created_at)

**Aggregator Worker (`aggregator.py`):**
- Runs as a background asyncio task
- Every 60 seconds: reads new entries from `query_log`, aggregates into `frequencies` table
- After aggregation: rebuilds the trie from updated frequencies
- Logs aggregation statistics (queries processed, new entries, rebuild time)

### Suggestion Filter (`filter.py`)

- Maintains a set of blocked queries loaded from `filter_list` table
- Applied before returning suggestions to users
- Supports adding/removing queries from the blocklist
- Filtered queries are removed from the trie asynchronously

### Frontend (Vue 3 + Vite)

**SearchBox Component:**
- Centered search input on a clean page
- 300ms debounce on input before calling API
- Dropdown showing top-5 suggestions with query text and frequency bar
- Click suggestion or press Enter to execute search
- Keyboard navigation: Up/Down arrows to select, Esc to close dropdown
- Shows "No suggestions" when no matches found

**API Integration:**
- `GET /api/suggestions?prefix=xxx` for autocomplete
- `POST /api/queries` to record confirmed searches

### Docker Deployment

- Backend: `python:3.11-slim`, uvicorn on port 8000
- Frontend: `node:20-alpine` build + `nginx:alpine` serving on port 8080
- Nginx proxies `/api/` to backend
- `docker-compose.yml` orchestrates both services

## Tech Stack

- **Backend:** Python 3.11, FastAPI, uvicorn, aiosqlite
- **Frontend:** Vue 3, Vite, Axios
- **Database:** SQLite (async via aiosqlite)
- **Deployment:** Docker, Docker Compose, Nginx

## Data Flow

1. User types in search box → debounced API call → Trie lookup → top-5 suggestions returned
2. User confirms search → POST to record query → written to `query_log` table
3. Background worker (every 60s) → aggregates `query_log` → updates `frequencies` → rebuilds Trie
4. Filter layer → blocks unwanted suggestions before returning to users
