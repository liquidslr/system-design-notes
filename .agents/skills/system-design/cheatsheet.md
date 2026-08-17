# Cheatsheet

The numbers and decision rules worth knowing cold. Every entry cites the chapter that backs it.

## Latency numbers (Ch 2)

| Operation | Latency |
|---|---|
| L1 cache access | 0.5 ns |
| L2 cache access | 7 ns |
| Main memory access | 100 ns |
| SSD random read | 150 µs |
| Round trip within a data center | 500 µs |
| HDD random seek | 10 ms |
| Inter-region round trip | 150 ms |

**Read it as**: memory is fast, disk is slow, cross-region is *very* slow. Avoid disk seeks; compress before sending over the internet.

## Availability (Ch 2)

| Nines | Downtime / year |
|---|---|
| 99% | ~3.65 days |
| 99.9% | ~8.8 hours |
| 99.99% | ~52 minutes |
| 99.999% | ~5.3 minutes |
| 99.9999% | ~31.6 seconds |

Major cloud SLAs target **99.9% or higher**.

## Interview time budget, 45 minutes (Ch 3)

| Step | Minutes |
|---|---|
| 1. Understand problem, establish scope | 3–10 |
| 2. High-level design + buy-in | 10–15 |
| 3. Deep dive | 10–25 |
| 4. Wrap up | 3–5 |

## Estimation drill (Ch 2)

The Twitter worked example, as a template:
- DAU = MAU × DAU-ratio → `300M × 50% = 150M`
- QPS = DAU × actions/day ÷ 86,400 → `150M × 2 ÷ 86400 ≈ 3,500`
- **Peak QPS = 2 × average QPS** → `~7,000`
- Storage/day = DAU × actions × media-ratio × size → `150M × 2 × 10% × 1MB = 30 TB/day`
- Multiply by retention → `30TB × 365 × 5 ≈ 55 PB`

Rules: round aggressively (`99987/9.1 → 100000/10`), write assumptions down, always label units.

## Quorum: pick W and R (Ch 6)

`N` = replicas, `W` = write acks required, `R` = read responses required.

| Goal | Setting |
|---|---|
| Strong consistency | **W + R > N** (typically N=3, W=R=2) |
| Fast reads | R = 1, W = N |
| Fast writes | W = 1, R = N |
| No consistency guarantee | W + R ≤ N |

## CAP: which side to give up (Ch 6)

CA is not achievable in a real distributed system — partitions happen.

| Choose | When | Behavior during a partition |
|---|---|---|
| **CP** | money, inventory, ledgers | block writes rather than diverge |
| **AP** | feeds, presence, analytics, caches | keep serving, allow stale reads, reconcile after |

## Rate limiting algorithms (Ch 4)

| Algorithm | Pros | Cons | Reach for it when |
|---|---|---|---|
| Token bucket | simple, memory-efficient, allows bursts | two params to tune | bursty traffic is legitimate |
| Leaking bucket | stable outflow rate, memory-efficient | bursts delay recent requests | downstream needs a steady rate |
| Fixed window counter | simplest | spikes at window edges exceed the quota | approximate limits are fine |
| Sliding window log | exact | high memory (a timestamp per request) | strict correctness matters |
| Sliding window counter | memory-efficient, smooths bursts | approximate | the usual default |

Store counters in Redis. In a distributed setup, race conditions are the hazard: use Lua scripts or sorted sets, not naive read-modify-write.

## Unique IDs (Ch 7)

| Approach | Verdict |
|---|---|
| DB auto-increment, multi-master | hard to scale, IDs not time-ordered |
| UUID (128-bit) | no coordination, but not 64-bit and not sortable |
| Ticket server | numeric and simple, but a single point of failure |
| **Snowflake** | the answer for 64-bit, time-sortable, decentralized |

Snowflake layout: **1 sign + 41 timestamp (ms) + 5 datacenter + 5 machine + 12 sequence**. That is 32 datacenters × 32 machines, and **4,096 IDs per machine per millisecond**. Keep clocks in line with NTP; clock drift is the failure mode.

## Short-URL encoding (Ch 8)

| | Base 62 conversion | Hash + collision resolution |
|---|---|---|
| Length | grows with ID | fixed |
| Needs an ID generator | yes | no |
| Collisions | impossible | possible, must resolve |
| Enumerable (security) | yes — next URL is guessable | no |

A **7-character** base-62 string covers ~3.5 trillion URLs. Use a Bloom filter to check existence cheaply before hitting the store.

## Geospatial index (Ch 16)

| Method | Pros | Cons |
|---|---|---|
| Geohash | easy to implement and update, fixed-radius search | fixed grid size, boundary issues |
| Quadtree | adapts to density, supports k-nearest | more complex, rebuilds are painful |
| Google S2 | strong geofencing, used in Google Maps | hardest to implement |

Rule: **geohash unless you need k-nearest or density adaptation**; then quadtree.

## Delivery semantics (Ch 19, Ch 21)

| Guarantee | Mechanism | Use when |
|---|---|---|
| At-most-once | fire and forget, commit offset before processing | loss is acceptable (metrics, logs) |
| At-least-once | producer retries with `ack=all`, consumer commits *after* processing | duplicates are tolerable or dedupable — the common default |
| Exactly-once | distributed transaction over offset + result | money is involved (billing, payments) — expensive |

If the downstream write is idempotent, at-least-once plus idempotency beats a distributed transaction.

## Fanout: write vs read (Ch 11)

| | Fanout on write | Fanout on read |
|---|---|---|
| Cost | heavy at write | heavy at read |
| Feed latency | fast | slow |
| Breaks on | users with huge follower counts | very active readers |

**Default to hybrid**: push for normal users, pull for celebrities. The same asymmetry appears as the "celebrity problem" hot shard in Ch 1.

## Consistent hashing (Ch 5)

- Ring spans `0` to `2^160 - 1` when hashing with SHA-1.
- Key → walk clockwise to the first server.
- Adding or removing a server only remaps the keys between it and its predecessor.
- **Always add virtual nodes** — more virtual nodes, smaller standard deviation, more even load. Without them you get uneven partitions and hotspots.

## Durability: replication vs erasure coding (Ch 24)

| | 3x replication | 8+4 erasure coding |
|---|---|---|
| Storage overhead | 200% | 50% |
| Durability | ~6 nines | ~11 nines |
| Read path | one node | gather 8 fragments |
| CPU | none | parity computation |

Replication for latency-sensitive data; erasure coding for cost and durability on colder data.

## Metrics retention (Ch 20)

~85% of queries to an operational store target the **last 26 hours** (Facebook). Down-sample old data on a schedule:

| Age | Resolution |
|---|---|
| ≤ 7 days | raw, no down-sampling |
| ≤ 30 days | 1 minute |
| ≤ 1 year | 1 hour |

Then move it to cold storage.

## Tells and smells

- Sharding proposed before caching and replication → you skipped rungs of the Ch 1 ladder.
- No number attached to a scale claim → run the Ch 2 drill instead.
- "Exactly-once" asserted without a distributed transaction or an idempotent sink → it is at-least-once (Ch 19, Ch 21).
- Consistent hashing without virtual nodes → hotspots incoming (Ch 5).
- One shard receiving disproportionate traffic → celebrity problem; give it a dedicated shard (Ch 1, Ch 11).
- Session state on the web tier → cannot autoscale (Ch 1).
- Cache with no eviction and no expiry policy → memory leak in production (Ch 1).
- A single cache server → single point of failure (Ch 1).
