---
name: system-design
description: "System design knowledge base built from the 28 chapters of these notes on Alex Xu's System Design Interview (Vol 1 & 2). Use when designing or reviewing a distributed system, preparing for a system design interview, doing back-of-the-envelope estimation, or choosing between rate limiting, consistent hashing, sharding, replication, caching, message queues, geospatial indexing, delivery semantics, or consistency models."
---

<!-- argument-hint: [topic, system name, or chapter number] -->

# System Design Notes

**Source**: [System Design Interview - An Insider's Guide, Vol 1 & 2](https://bytebytego.com/courses/system-design-interview) by Alex Xu | **Chapters**: 28

## How to Use This Skill

1. **Match the request to a topic** in the Topic Index below.
2. **Read the chapter file** listed for it before answering. Do not answer detailed design questions from memory — the chapters carry the numbers, tables, and trade-offs.
3. **Cite the chapter** you used, so the user can go deeper.

### Locating a chapter file

Every row in the Chapter Index gives a repo-relative path. Resolve it in this order:

1. **Inside the repo** (this skill's usual home): read `<repo-root>/<path>`. From this skill directory that is `../../../<path>` — e.g. `../../../04. Rate Limiter/Readme.md`.
2. **Installed elsewhere** (e.g. via `npx skills add`, so the notes are not on disk): fetch
   `https://raw.githubusercontent.com/liquidslr/system-design-notes/main/<path>`, URL-encoding the spaces as `%20`.

Filenames are case-sensitive on Linux and on raw.githubusercontent.com: chapters 1–16 use `Readme.md`, chapters 17–28 use `README.md`. Chapter 27's directory contains **two** spaces after the period.

---

## Core Frameworks

### The 4-step interview framework (Ch 3)
The spine of every design discussion. Budget for a 45-minute interview:

1. **Understand the problem, establish scope** (3–10 min) — ask clarifying questions, write assumptions down. Never design before the requirements are pinned.
2. **Propose a high-level design, get buy-in** (10–15 min) — box diagram, back-of-the-envelope check, walk one use case end to end. Treat the interviewer as a teammate.
3. **Design deep dive** (10–25 min) — pick the components that actually carry the problem, discuss bottlenecks. Neither over-engineer nor skim.
4. **Wrap up** (3–5 min) — name the bottlenecks, recap trade-offs, propose what changes at 10x scale.

**Don'ts**: premature solutions, going silent, over-engineering.

### The scaling ladder (Ch 1)
Apply in order; each rung buys headroom for the next. Single server → separate DB tier → load balancer + horizontal web tier → primary/replica DB replication → cache tier → CDN for static assets → stateless web tier (sessions in a shared store) → multi-data-center + GeoDNS → message queue for async work → logging/metrics/automation → database sharding.

**Invariants**: keep the web tier stateless, build redundancy at every tier, decouple with queues, shard the data tier last.

### CAP and the consistency dial (Ch 6)
Partitions are unavoidable, so **CA does not exist in practice** — the real choice is CP or AP.
- **CP** — block writes during a partition rather than diverge (banking, ledgers, inventory).
- **AP** — keep serving, accept stale reads, reconcile later (feeds, presence, analytics).

Tune it with quorum: `N` replicas, `W` write acks, `R` read responses. **`W + R > N` gives strong consistency** (typically N=3, W=R=2). `R=1, W=N` optimizes reads; `W=1, R=N` optimizes writes.

### Choosing where work happens
- **Fanout on write vs on read** (Ch 11) — push at write time for fast reads; pull at read time for cheap writes. Hybrid: push for normal users, pull for celebrities. The same "celebrity problem" shows up as a hot shard in Ch 1.
- **Streaming vs batching** (Ch 21) — streaming for low latency, batching for accuracy and cheap reprocessing. Billing-grade data usually needs both (lambda-style).
- **Push vs pull metrics collection** (Ch 20) — pull scales via service discovery, push suits short-lived jobs.

### Trade-off axes to name out loud
Latency vs consistency · memory vs accuracy · write cost vs read cost · simplicity vs adaptivity · duplication vs loss (delivery semantics) · cost vs availability (replication factor).

---

## Chapter Index

| # | Title | Key topics | Path |
|---|-------|-----------|------|
| 1 | Scale From Zero To Millions | load balancing, replication, cache, CDN, sharding | `01. Scaling/Readme.md` |
| 2 | Back-of-the-Envelope Estimation | latency numbers, availability nines, QPS/storage math | `02. Back Of the Envelope Estimation/Readme.md` |
| 3 | A Framework For System Design Interviews | the 4-step framework, time budget | `03. System Design Framework/Readme.md` |
| 4 | Design A Rate Limiter | token/leaking bucket, sliding window, Redis | `04. Rate Limiter/Readme.md` |
| 5 | Design Consistent Hashing | hash ring, virtual nodes, rehashing problem | `05. Consistent Hashing/Readme.md` |
| 6 | Design A Key-Value Store | CAP, quorum, vector clocks, Merkle trees, gossip | `06. Key-Value Store/Readme.md` |
| 7 | Unique ID Generator | Snowflake, UUID, ticket server, clock drift | `07. Unique-Id Generator/Readme.md` |
| 8 | Design A URL Shortener | base62, hash collisions, 301 vs 302 | `08. URL Shortener/Readme.md` |
| 9 | Design A Web Crawler | URL frontier, politeness, BFS, trap avoidance | `09. Web Crawler/Readme.md` |
| 10 | Design A Notification System | APNS/FCM/SMS/email, retries, dedup | `10. Notification System/Readme.md` |
| 11 | Design A News Feed System | fanout on write vs read, feed cache | `11. News Feed System/Readme.md` |
| 12 | Design A Chat System | WebSocket vs polling, presence, service discovery | `12. Chat System/Readme.md` |
| 13 | Search Autocomplete | trie, prefix cache, data gathering pipeline | `13. Search Autocomplete/Readme.md` |
| 14 | Design YouTube | transcoding DAG, codecs/containers, GOP chunks, CDN cost | `14. Youtube/Readme.md` |
| 15 | Design Google Drive | block-level sync, delta sync, dedup, metadata DB | `15. Google Drive/Readme.md` |
| 16 | Proximity Service | geohash, quadtree, Google S2, geospatial index | `16. Proximity Service/Readme.md` |
| 17 | Nearby Friends | Redis pub/sub, location TTL, fan-out to friends | `17. Nearby Friends/README.md` |
| 18 | Design Google Maps | tiles, routing, ETA, map rendering, geocoding | `18. Google Maps/README.md` |
| 19 | Distributed Message Queue | partitions, consumer groups, ISR, delivery semantics | `19. Distributed Message Queue/README.md` |
| 20 | Metrics Monitoring & Alerting | time-series DB, pull vs push, downsampling | `20. Metrics Monitoring and Alerting System/README.md` |
| 21 | Ad Click Event Aggregation | streaming vs batching, watermarks, exactly-once, dedup | `21. Ad Click Event Aggregation/README.md` |
| 22 | Hotel Reservation System | inventory concurrency, optimistic vs pessimistic locking, Saga | `22. Hotel Reservation System/README.md` |
| 23 | Distributed Email Service | SMTP/IMAP, metadata DB, search index | `23. Distributed Email Service/README.md` |
| 24 | S3-like Object Storage | erasure coding vs replication, versioning, GC | `24. S3-like Object Storage/README.md` |
| 25 | Real-time Gaming Leaderboard | Redis sorted sets, sharding by score, NoSQL alternative | `25. Real-time Gaming Leaderboard/README.md` |
| 26 | Payment System | double-entry ledger, PSP, reconciliation, idempotency | `26. Payment System/README.md` |
| 27 | Digital Wallet | TC/C, Saga, event sourcing, CQRS, Raft | `27.  Digital Wallet/README.md` |
| 28 | Stock Exchange | matching engine, event sourcing, determinism, colocation | `28. Stock Exchange/README.md` |

## Topic Index

- **Aggregation windows, watermarks** → ch21
- **Availability / nines** → ch02, ch01
- **Bloom filter** → ch06
- **CAP theorem** → ch06
- **Caching** → ch01, ch11, ch13, ch16
- **CDN** → ch01, ch14
- **Concurrency control, locking** → ch22, ch27
- **Consistency models** → ch06, ch22, ch26
- **Consistent hashing** → ch05, ch06, ch01
- **Deduplication** → ch10, ch15, ch21, ch26
- **Delivery semantics (at-most/at-least/exactly once)** → ch19, ch21, ch26
- **Distributed transactions (2PC, TC/C, Saga)** → ch22, ch26, ch27
- **Erasure coding** → ch24
- **Estimation (QPS, storage)** → ch02, and the "Back-of-the-envelope" section of ch16–ch28
- **Event sourcing / CQRS** → ch27, ch28
- **Fanout (write vs read)** → ch11, ch17
- **Failure detection, gossip** → ch06
- **Geospatial indexing (geohash, quadtree, S2)** → ch16, ch17, ch18
- **Idempotency** → ch26, ch21
- **Interview framework, time budget** → ch03
- **Latency numbers** → ch02
- **Leader election, Raft, ZooKeeper** → ch19, ch27
- **Ledger, double-entry** → ch26, ch27
- **Load balancing** → ch01
- **Long polling / WebSocket** → ch12, ch17
- **Matching engine** → ch28
- **Merkle tree** → ch06
- **Message queue, partitions, consumer groups** → ch19, ch01, ch21
- **Metadata database design** → ch15, ch23, ch24
- **Monitoring, alerting, time-series** → ch20, ch01
- **Quorum (N, W, R)** → ch06
- **Rate limiting** → ch04, ch08, ch09
- **Replication (primary/replica, ISR)** → ch01, ch06, ch19, ch24
- **Sharding, resharding, hot shards** → ch01, ch05, ch25, ch27
- **Snowflake / unique IDs** → ch07
- **Sorted sets (Redis)** → ch25
- **Streaming vs batching** → ch21, ch20
- **Sync (delta, differential)** → ch15
- **Transcoding** → ch14
- **Trie** → ch13
- **Vector clocks** → ch06
- **Versioning** → ch06, ch24
- **Web crawling, URL frontier** → ch09

## Supporting Files

- [cheatsheet.md](cheatsheet.md) — the numbers and decision rules worth memorizing
- [patterns.md](patterns.md) — recurring techniques and when to reach for each
- [glossary.md](glossary.md) — terms with the chapter that defines them

---

## Scope & Limits

These notes are a work in progress and cover the book's material only — they are summaries, not the book text. Diagrams live as images next to each chapter and are not reproduced here; when a chapter's answer hinges on a diagram, say so and point the user at the file. For implementation in a real codebase, combine with the project's own context.
