# Glossary

Terms with the chapter that introduces them. Read that chapter for the full treatment.

**At-least-once** — delivery guarantee where a message is never lost but may arrive more than once; the common default, paired with dedup or idempotency (Ch 19, 21)

**At-most-once** — delivery guarantee where a message is never duplicated but may be lost (Ch 19, 21)

**Availability (nines)** — uptime expressed as 99.9%, 99.99%, etc.; see the downtime table in the cheatsheet (Ch 2)

**Back-of-the-envelope estimation** — quick order-of-magnitude sizing of QPS, storage, and servers to sanity-check a design (Ch 2)

**Base 62 conversion** — encoding an integer ID with `[0-9a-zA-Z]` to produce a short URL (Ch 8)

**Bloom filter** — probabilistic set membership structure; false positives possible, false negatives impossible (Ch 6, 8)

**CAP theorem** — a distributed system can guarantee at most two of consistency, availability, and partition tolerance; since partitions are unavoidable, the real choice is CP or AP (Ch 6)

**CDN** — geographically distributed cache for static content, close to the user (Ch 1, 14)

**Celebrity problem** — one entity attracts so much traffic that its shard or its fanout dominates the system (Ch 1, 11)

**Codec** — the compression/decompression algorithm for a media stream, e.g. H.264, VP9 (Ch 14)

**Cold storage** — cheap, slow storage for data that is rarely accessed (Ch 15, 20)

**Consistent hashing** — mapping keys and servers onto a ring so membership changes remap only a fraction of keys (Ch 5, 6)

**Container (media)** — the file format wrapping video, audio, and metadata, e.g. MP4, AVI (Ch 14)

**CQRS** — separating the write model from read-optimized projections (Ch 27)

**Delta sync** — transferring only the blocks of a file that changed (Ch 15)

**Double-entry ledger** — accounting scheme where each transaction writes two balanced entries so the books always sum to zero (Ch 26, 27)

**Down-sampling** — reducing the resolution of old time-series data to save space (Ch 20)

**Erasure coding** — storing data plus parity fragments so the original can be reconstructed from a subset; cheaper than replication at higher durability (Ch 24)

**Eventual consistency** — given enough time and no new writes, all replicas converge (Ch 6)

**Event sourcing** — treating an append-only event log as the source of truth, with state derived by replaying it (Ch 27, 28)

**Exactly-once** — delivery guarantee with no loss and no duplicates; requires a distributed transaction or an idempotent sink (Ch 19, 21)

**Fanout on read** — assembling a feed at read time by pulling from the sources (Ch 11)

**Fanout on write** — pushing a new item into every recipient's feed at publish time (Ch 11)

**Geohash** — encoding a lat/lng into a short string whose prefix denotes a bounding box (Ch 16)

**Gossip protocol** — nodes exchange heartbeat counters with random peers to detect failures without a coordinator (Ch 6)

**GOP alignment** — splitting video at group-of-pictures boundaries so chunks can be transcoded independently (Ch 14)

**Hinted handoff** — writing to a substitute node when the owner is down, then replaying to the owner on recovery (Ch 6)

**Horizontal scaling** — adding more machines behind a load balancer (Ch 1)

**Idempotency** — a repeated operation produces the same result as a single one (Ch 21, 26)

**In-sync replica (ISR)** — a replica that is sufficiently caught up with the leader to be eligible for promotion (Ch 19)

**Leaking bucket** — rate limiter that processes requests from a FIFO queue at a fixed rate (Ch 4)

**Load balancer** — distributes traffic across servers, giving redundancy and easy scale-out (Ch 1)

**LRU** — least-recently-used, the most common cache eviction policy (Ch 1)

**Matching engine** — the component of an exchange that pairs buy and sell orders (Ch 28)

**Merkle tree** — tree of hashes that lets two replicas find exactly which data differs without transferring it all (Ch 6)

**Message queue** — durable buffer enabling asynchronous, decoupled communication between producers and consumers (Ch 1, 19)

**Optimistic concurrency control** — read a version, write conditionally on it, retry on conflict (Ch 22)

**Partition (message queue)** — the unit of parallelism and ordering within a topic (Ch 19)

**Partition tolerance** — continuing to operate despite network splits (Ch 6)

**Pessimistic concurrency control** — lock the resource for the duration of the operation (Ch 22)

**Quadtree** — recursive 2D space partition that adapts to point density and supports k-nearest queries (Ch 16)

**Quorum consensus** — requiring W write acks and R read responses out of N replicas; `W + R > N` yields strong consistency (Ch 6)

**Rate limiter** — component that caps how many requests a client may make in a window (Ch 4)

**Reconciliation** — comparing internal records against an external source of truth (e.g. a payment processor's settlement file) to find discrepancies (Ch 26)

**Replication (primary/replica)** — writes go to the primary, reads fan out to replicas (Ch 1)

**Resharding** — redistributing data when shards outgrow capacity or become unbalanced (Ch 1)

**Saga** — a sequence of local transactions, each with a compensating action, used instead of a blocking distributed transaction (Ch 22, 26, 27)

**S2 (Google S2)** — hierarchical spherical geometry library used for geofencing and geospatial indexing (Ch 16)

**Sharding** — splitting a dataset across servers by a sharding key (Ch 1)

**Sliding window counter** — rate limiter that blends fixed windows with a weighted look-back to smooth edge spikes (Ch 4)

**Sliding window log** — rate limiter that stores a timestamp per request for exact limits at high memory cost (Ch 4)

**Sloppy quorum** — satisfying W and R from the first *healthy* nodes rather than the designated replicas (Ch 6)

**Snowflake** — Twitter's 64-bit ID scheme packing timestamp, datacenter, machine, and sequence (Ch 7)

**Sorted set** — Redis structure supporting score-ordered ranking and rank queries (Ch 25)

**SSTable** — Sorted String Table, the immutable on-disk file an LSM store flushes to (Ch 6)

**Stateless web tier** — web servers hold no session state, so any request can go to any server (Ch 1)

**Strong consistency** — a read always returns the most recent write (Ch 6)

**TC/C (Try-Confirm/Cancel)** — two-phase distributed transaction that reserves resources in a Try phase, then Confirms or Cancels (Ch 27)

**Ticket server** — a centralized database used solely to hand out incrementing IDs (Ch 7)

**Time-series database** — storage optimized for timestamped metrics, with encoding and down-sampling built in (Ch 20)

**Token bucket** — rate limiter where tokens accrue at a fixed rate and each request spends one; allows bursts (Ch 4)

**Transcoding** — converting a video into other resolutions, bitrates, and codecs (Ch 14)

**Trie** — prefix tree used for autocomplete, with top-k results cached at each node (Ch 13)

**URL frontier** — the queue structure that manages which URLs a crawler visits next, enforcing priority and politeness (Ch 9)

**UUID** — 128-bit identifier generated without coordination; not 64-bit and not time-sortable (Ch 7)

**Vector clock** — set of `[server, counter]` pairs used to determine whether two versions are causally ordered or in conflict (Ch 6)

**Vertical scaling** — adding CPU/RAM to an existing machine; limited and offers no redundancy (Ch 1)

**Virtual node** — multiple ring positions per physical server, used to even out load in consistent hashing (Ch 5, 6)

**Watermark** — in stream processing, the marker of how far event time has advanced, used to close aggregation windows (Ch 21)

**WebSocket** — persistent bidirectional connection for real-time client/server messaging (Ch 12)

**Weak consistency** — reads may not see the most recent write, with no convergence guarantee stated (Ch 6)

**ZooKeeper** — coordination service used for metadata, leader election, and service discovery (Ch 19, 20)
