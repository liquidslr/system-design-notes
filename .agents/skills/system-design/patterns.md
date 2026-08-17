# Patterns

Recurring techniques across the 28 chapters, with the situation that calls for each. Read the cited chapter before designing with one.

## Consistent hashing with virtual nodes
**When**: distributing keys, sessions, or shards across a server pool whose size changes.
**How**: hash servers and keys onto a ring; a key belongs to the first server clockwise. Give each server many virtual nodes so load evens out.
**Trade-offs**: only a fraction of keys move on membership change, versus plain `hash(key) % N` which remaps almost everything. Costs ring bookkeeping.
**Chapters**: 5, 6, 1. Used by Dynamo, Cassandra, Discord, Akamai, Maglev.

## Quorum reads and writes
**When**: replicated storage that needs a tunable consistency/latency dial.
**How**: pick N, W, R. `W + R > N` for strong consistency.
**Trade-offs**: every point on the curve trades latency for freshness. Sloppy quorum (first W/R *healthy* nodes) keeps you available during transient failures at the cost of strictness.
**Chapter**: 6.

## Vector clocks
**When**: concurrent writes to the same key on different replicas, and last-write-wins is unacceptable.
**How**: carry `[server, counter]` pairs with each version. X precedes Y if every counter in X ≤ Y; otherwise the versions are siblings and conflict.
**Trade-offs**: correct conflict detection, but the client must resolve siblings, and the clock grows without a trimming strategy.
**Chapter**: 6.

## Merkle tree anti-entropy
**When**: two replicas drifted apart after a long outage and you need to find *which* data differs without shipping all of it.
**How**: bucket the key space, hash each bucket, build a tree of hashes. Compare roots; descend only into subtrees that differ.
**Trade-offs**: synchronization traffic proportional to the diff, not the dataset.
**Chapter**: 6.

## Gossip failure detection
**When**: deciding a node is dead in a decentralized cluster.
**How**: every node keeps heartbeat counters for members, increments its own, and periodically gossips to random peers. A counter that stops advancing past a threshold marks the node offline.
**Trade-offs**: no central coordinator, no single point of failure; detection is eventual, not instant. Require at least two independent sources before declaring a node down.
**Chapter**: 6.

## Hinted handoff and sloppy quorum
**When**: a replica is temporarily unreachable but you still want to accept writes.
**How**: write to the next healthy node with a hint about the intended owner; replay to the owner when it returns.
**Trade-offs**: preserves availability during blips; adds reconciliation work and a window of divergence.
**Chapter**: 6.

## LSM write path (commit log → memtable → SSTable)
**When**: write-heavy storage.
**How**: append to a commit log for durability, buffer in memory, flush sorted runs to disk. On read, check the memtable, then use a Bloom filter to pick which SSTables to touch.
**Trade-offs**: fast sequential writes, reads may span multiple files. Follows Cassandra's architecture.
**Chapter**: 6.

## Bloom filter as a negative-lookup gate
**When**: you want to avoid an expensive lookup for keys that probably do not exist.
**How**: check the filter first; a negative answer is certain, a positive answer needs verification.
**Trade-offs**: constant memory, false positives only.
**Chapters**: 6 (SSTable lookup), 8 (short-URL existence check).

## Snowflake-style ID composition
**When**: 64-bit, roughly time-sortable IDs generated without coordination.
**How**: pack timestamp, datacenter, machine, and a per-millisecond sequence into one integer. Tune section widths to your throughput.
**Trade-offs**: no central bottleneck; depends on clock sync (NTP) and is vulnerable to clock skew.
**Chapter**: 7.

## Fanout on write / on read / hybrid
**When**: any feed, timeline, or subscriber-notification system.
**How**: precompute recipient feeds at publish time, or assemble at read time, or split by follower count.
**Trade-offs**: the write/read cost asymmetry is the whole decision. Store `<post_id, user_id>` in the feed cache rather than full objects, and cap the stored window.
**Chapters**: 11, 17.

## Message queue for decoupling
**When**: producers and consumers should scale, fail, and deploy independently.
**How**: topics partitioned across brokers, consumer groups for parallelism, in-sync replicas for durability, offsets committed by the consumer.
**Trade-offs**: buys buffering and independent scaling; adds delivery-semantics decisions and rebalance complexity.
**Chapters**: 19, 1, 21.

## Deduplication with stored offsets
**When**: at-least-once delivery meets data that must be counted once (billing, ad clicks).
**How**: persist the consumed offset atomically with the downstream write, i.e. a distributed transaction.
**Trade-offs**: expensive. If the sink can absorb the same result twice without changing the outcome, make it idempotent instead and skip the transaction.
**Chapters**: 21, 26.

## Distributed transactions: 2PC, TC/C, Saga
**When**: one logical operation spans services or shards.
**How**: 2PC blocks and holds locks. TC/C reserves in a Try phase then Confirms or Cancels. Saga runs local transactions in order with a compensating action for each.
**Trade-offs**: 2PC is strongly consistent but fragile and blocking; TC/C and Saga are eventually consistent and need explicit compensation logic for every step.
**Chapters**: 27, 22, 26.

## Event sourcing and CQRS
**When**: auditability, replay, or deterministic reconstruction matters — wallets, ledgers, exchanges.
**How**: the event log is the source of truth; state is a fold over it. Read models are projections built off the log.
**Trade-offs**: perfect audit trail and reproducibility; read models are eventually consistent and the log needs snapshots to keep replay bounded.
**Chapters**: 27, 28.

## Optimistic vs pessimistic concurrency control
**When**: two clients race for the same finite resource (a hotel room, a seat, a balance).
**How**: pessimistic locks the row for the duration; optimistic reads a version, then writes conditionally on that version and retries on mismatch.
**Trade-offs**: pessimistic is simple but serializes and risks deadlock; optimistic scales under low contention and degrades under high contention.
**Chapter**: 22.

## Double-entry ledger
**When**: any system that moves money.
**How**: every transaction writes two balanced entries. The sum across accounts is always zero.
**Trade-offs**: makes reconciliation and audit tractable; more writes per operation.
**Chapters**: 26, 27.

## Geospatial indexing
**When**: "what is near me" queries.
**How**: encode 2D location into a 1D key (geohash) or a density-adaptive tree (quadtree, S2), then index that key.
**Trade-offs**: see the Ch 16 comparison table in the cheatsheet. A plain 2D range query on lat/lng does not scale.
**Chapters**: 16, 17, 18.

## Trie for prefix search
**When**: autocomplete and typeahead.
**How**: store top-k completions at each node so a lookup is a walk plus a read, not a subtree scan. Cache hot prefixes; rebuild the trie offline from an aggregation pipeline.
**Trade-offs**: fast reads, expensive rebuilds — which is why the data-gathering pipeline is asynchronous.
**Chapter**: 13.

## Redis sorted sets for ranking
**When**: leaderboards and any "top N by score" query.
**How**: one sorted set per leaderboard; score updates and rank queries are logarithmic.
**Trade-offs**: excellent latency, bounded by memory. Shard by score range or use a NoSQL alternative when the set outgrows one instance.
**Chapter**: 25.

## Chunked upload and delta sync
**When**: large files over unreliable networks.
**How**: split into blocks, hash each, transfer only changed blocks, deduplicate identical blocks, and resume from the last acknowledged chunk.
**Trade-offs**: much less bandwidth and better failure recovery; needs a metadata database tracking block hashes.
**Chapters**: 15, 24.

## Erasure coding vs replication
**When**: durable bulk storage.
**How**: replication stores N full copies; erasure coding stores data plus parity fragments (e.g. an 8+4 scheme spread across failure domains) and reconstructs from any sufficient subset.
**Trade-offs**: 3x replication costs **200% storage overhead and gives 6 nines** of durability; **8+4 erasure coding costs 50% overhead and gives 11 nines** — but reads must gather fragments from several nodes and parity computation costs CPU. Replication for latency-sensitive data, erasure coding for cost and durability.
**Chapter**: 24.

## Push vs pull metrics collection
**When**: gathering metrics from many hosts.
**How**: pull scrapes a `/metrics` endpoint on each target, with the target list kept in service discovery (ZooKeeper or etcd); push has each service send to a collector proactively.
**Trade-offs**: occasional loss is acceptable for metrics, so fire-and-forget is fine either way. Pull needs an accurate service-discovery list *and* a way to stop two collectors scraping the same target — put collectors and servers on a consistent hash ring so each server belongs to exactly one collector.
**Chapter**: 20.

## WebSocket over polling
**When**: server-initiated messages — chat, presence, live location.
**How**: one persistent bidirectional connection instead of repeated requests.
**Trade-offs**: real-time delivery and no polling overhead; connections are stateful, so you need service discovery and careful capacity planning per server.
**Chapters**: 12, 17.
