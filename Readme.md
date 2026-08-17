
# [System Design Interview - An Insider's Guide (Vol 1 and 2)](https://bytebytego.com/courses/system-design-interview)
These notes are based on the System Design Interview books - [Vol 1 and Vol 2 2nd Ed](https://www.goodreads.com/book/show/54109255-system-design-interview-an-insider-s-guide) 

Check the notes here: https://pagefy.io/system-design/system-design-interview-by-alex-xu

**Note:** These notes are a work in progress. 


 * [Chapter 1 - Scale From Zero To Millions Of Users](./01.%20Scaling/)
 * [Chapter 2 - Back-of-the-envelope Estimation](./02.%20Back%20Of%20the%20Envelope%20Estimation/)
 * [Chapter 3 - A Framework For System Design Interviews](./03.%20System%20Design%20Framework/)
 * [Chapter 4 - Design A Rate Limiter](./04.%20Rate%20Limiter//)
 * [Chapter 5 - Design Consistent Hashing](./05.%20Consistent%20Hashing/)
 * [Chapter 6 - Design A Key-Value Store](./06.%20Key-Value%20Store/)
 * [Chapter 7 - Design A Unique ID Generator In Distributed Systems](./07.%20Unique-Id%20Generator/)
 * [Chapter 8 - Design A URL Shortener](./08.%20URL%20Shortener/)
 * [Chapter 9 - Design A Web Crawler](./09.%20Web%20Crawler/)
 * [Chapter 10 - Design A Notification System](./10.%20Notification%20System/)
 * [Chapter 11 - Design A News Feed System](./11.%20News%20Feed%20System/)
 * [Chapter 12 - Design A Chat System](./12.%20Chat%20System/)
 * [Chapter 13 - Design A Search Autocomplete System](./13.%20Search%20Autocomplete/)
 * [Chapter 14 - Design YouTube](./14.%20Youtube/)
 * [Chapter 15 - Design Google Drive](./15.%20Google%20Drive/)
 * [Chapter 16 - Proximity Service](./16.%20Proximity%20Service/)
 * [Chapter 17 - Nearby Friends](./17.%20Nearby%20Friends/)
 * [Chapter 18 - Design Google Maps](./18.%20Google%20Maps/)
 * [Chapter 19 - Distributed Message Queue](./19.%20Distributed%20Message%20Queue/)
 * [Chapter 20 - Metrics Monitoring and Alerting System](./20.%20Metrics%20Monitoring%20and%20Alerting%20System/)
 * [Chapter 21 - Ad Click Event Aggregation](./21.%20Ad%20Click%20Event%20Aggregation/)
 * [Chapter 22 - Hotel Reservation System](./22.%20Hotel%20Reservation%20System/)
 * [Chapter 23 - Distributed Email Service](./23.%20Distributed%20Email%20Service/)
 * [Chapter 24 - S3-like Object Storage](./24.%20S3-like%20Object%20Storage/)
 * [Chapter 25 - Real-time Gaming Leaderboard](./25.%20Real-time%20Gaming%20Leaderboard/)
 * [Chapter 26 - Payment System](./26.%20Payment%20System/)
 * [Chapter 27 - Digital Wallet](./27.%20%20Digital%20Wallet/)
 * [Chapter 28 - Stock Exchange](./28.%20Stock%20Exchange/)


# Use these notes with an AI coding agent

These notes ship as an [Agent Skill](https://skills.sh), so Claude Code, Amp, Codex, Cursor and other
agent hosts can look up the right chapter instead of guessing from memory.

**Already cloned this repo?** Nothing to install. Opening it in Claude Code or Amp picks the skill up
automatically. Ask things like *"what quorum settings give strong consistency?"* or
*"walk me through designing a rate limiter"* and the agent reads the matching chapter first.

**Want it anywhere else?**

```bash
npx skills add liquidslr/system-design-notes --skill system-design
```

Installed outside the repo, the skill fetches chapters from GitHub instead of the local files.

The skill lives in [`.agents/skills/system-design/`](./.agents/skills/system-design/) and adds a
topic index over the 28 chapters plus three files that are not in the notes themselves: a
[cheatsheet](./.agents/skills/system-design/cheatsheet.md) of the numbers and decision rules worth
memorising, a [patterns](./.agents/skills/system-design/patterns.md) index of recurring techniques,
and a [glossary](./.agents/skills/system-design/glossary.md). Chapter content is not duplicated —
the chapter files above stay the single source of truth.

# Additonal Resources

### Rate Limiting
- [Circuit Breaker Algorithm](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Uber Rate Limiter](https://github.com/uber-go/ratelimit/blob/master/ratelimit.go)


### Consistent Hashing
- [Consistent Hashing](https://tom-e-white.com/2007/11/consistent-hashing.html)
- [CS168: Introduction and Consistent Hashing:]( http://theory.stanford.edu/~tim/s16/l/l1.pdf)
- [Apache Cassandra](http://www.cs.cornell.edu/Projects/ladis2009/papers/Lakshman-ladis2009.PDF)
- [Scaling Discord](https://blog.discord.com/scaling-elixir-f9b8e1e7c29b)
- [Google Maglev](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/44824.pdf)


### Key-Value Store
- [Amazon Dynamo](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)
- [Cassandra Architecture](https://docs.datastax.com/en/archived/cassandra/3.0/cassandra/architecture/archIntro.html)
- [Google BigTable Architecture](https://static.googleusercontent.com/media/research.google.com/en//archive/bigtable-osdi06.pdf)
- [Amazon Dynamo DB Internals](https://www.allthingsdistributed.com/2007/10/amazons_dynamo.html)
- [Design Patterns in Amazon Dynamo DB](https://www.youtube.com/watch?v=HaEPXoXVf2k)
- [Internals of Amazon Dynamo DB](https://www.youtube.com/watch?v=yvBR71D0nAQ)


### Unique-ID Generator
- [Ticket Servers: Distributed Unique Primary Keys on the Cheap](https://code.flickr.net/2010/02/08/ticket-servers-distributed-unique-primary-keys-on-the-cheap)
- [Snowflake](https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake.html)


### Web Crawler
- [Web Crawling](http://infolab.stanford.edu/~olston/publications/crawling_survey.pdf)
- [Google Dynamic Rendering](https://developers.google.com/search/docs/guides/dynamic-rendering)



### Chat Systems
- [How Discord stores billions of messages](https://discord.com/blog/how-discord-stores-billions-of-messages)
- [Flannel: An Application-Level Edge Cache to Make Slack Scale](https://slack.engineering/flannel-an-application-level-edge-cache-to-make-slack-scale/)


### Search Autocomplete
- [How We Built Prefixy](https://medium.com/@prefixyteam/how-we-built-prefixy-a-scalable-prefix-search-service-for-powering-autocomplete-c20f98e2eff1)
- [Prefix Hash Tree](https://people.eecs.berkeley.edu/~sylvia/papers/pht.pdf)


### Youtube
- [YouTube Architecture](http://highscalability.com/youtube-architecture)
- [YouTube scalability 2012](https://www.youtube.com/watch?v=w5WVu624fY8)
- [Transcoding Videos at Scale](https://www.egnyte.com/blog/2018/12/transcoding-how-we-serve-videos-at-scale/)
- [Facebook Video Broadcasting](https://engineering.fb.com/ios/under-the-hood-broadcasting-live-video-to-millions/)
- [Netflix Video Encoding at Scale](https://netflixtechblog.com/high-quality-video-encoding-at-scale-d159db052746)
- [Netflix Shot based encoding](https://netflixtechblog.com/optimized-shot-based-encodes-now-streaming-4b9464204830)


### Google Drive
- [Differential Synchronization](https://neil.fraser.name/writing/sync/)
- [Differential Synchronization Video](https://www.youtube.com/watch?v=S2Hp_1jqpY8)
- [How We’ve Scaled Dropbox](https://www.youtube.com/watch?v=PE4gwstWhmc&feature=youtu.be)
