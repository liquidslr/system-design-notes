"""
News Feed System — CLI Entry Point & Demo

Usage:
    python news-feed-system/__main__.py --demo     # Run demo
    python news-feed-system/__main__.py --server   # Run API server
"""
import argparse
import asyncio
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import FeedConfig
from app.database import Database
from app.cache import CacheLayer
from app.fanout import FanoutService
from app.service import FeedService


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


async def run_demo():
    """Run a demonstration of the news feed system."""
    print("=" * 60)
    print("  NEWS FEED SYSTEM — DEMO")
    print("=" * 60)
    print()

    config = FeedConfig(fanout_worker_count=3, fanout_threshold=500)
    db = Database(config)
    cache = CacheLayer(config)
    fanout = FanoutService(config, db, cache)
    service = FeedService(config, db, cache, fanout)

    await db.initialize()
    await fanout.start()

    try:
        # --- Step 1: Create users ---
        print("[1] Creating users...")
        users = [
            ("alice", "Alice"), ("bob", "Bob"), ("charlie", "Charlie"),
            ("diana", "Diana"), ("eve", "Eve"),
        ]
        for uid, name in users:
            await service.create_user(uid, uid, name)
            print(f"    Created user: {name} (@{uid})")

        # --- Step 2: Build social graph ---
        print("\n[2] Building social graph (friendships)...")
        friendships = [
            ("alice", "bob"), ("alice", "charlie"), ("alice", "diana"),
            ("bob", "charlie"), ("bob", "eve"),
            ("charlie", "diana"), ("charlie", "eve"),
            ("diana", "eve"),
        ]
        for u, f in friendships:
            await service.add_friend(u, f)
            print(f"    {u} ↔ {f}")

        # --- Step 3: Users publish posts ---
        print("\n[3] Users publishing posts...")
        posts_data = [
            ("alice", "Just finished reading a great book on system design! 📚"),
            ("bob", "Beautiful sunset at the beach today 🌅"),
            ("charlie", "Excited to announce my new open source project! 🚀"),
            ("diana", "Coffee + coding = perfect morning ☕💻"),
            ("alice", "Who else is attending the tech conference next week?"),
            ("eve", "Just deployed my first microservice! 🎉"),
            ("bob", "Hiking trip this weekend, who's in? 🏔️"),
        ]

        for user_id, content in posts_data:
            post = await service.create_post(user_id, content)
            print(f"    [{user_id:8s}] {content[:50]}...")

        # Wait for fanout to complete
        await asyncio.sleep(1)

        # --- Step 4: View news feeds ---
        print("\n[4] Viewing news feeds (reverse chronological):")
        for user_id in ["alice", "bob", "charlie", "diana", "eve"]:
            feed = await service.get_feed(user_id, page_size=5)
            print(f"\n    📰 {user_id}'s feed ({len(feed)} posts):")
            for p in feed:
                author = p.user_id
                ts = time.strftime("%H:%M:%S", time.localtime(p.created_at))
                print(f"       [{ts}] @{author}: {p.content[:45]}...")

        # --- Step 5: Actions ---
        print("\n[5] Performing actions (likes, replies, shares)...")
        # Get a post to interact with
        alice_feed = await service.get_feed("alice", page_size=1)
        if alice_feed:
            target_post = alice_feed[0]
            await service.like_post("bob", target_post.post_id)
            await service.like_post("charlie", target_post.post_id)
            await service.reply_to_post("diana", target_post.post_id, "Great post! 👍")
            await service.share_post("eve", target_post.post_id)
            print(f"    Bob liked @{target_post.user_id}'s post")
            print(f"    Charlie liked @{target_post.user_id}'s post")
            print(f"    Diana replied: 'Great post! 👍'")
            print(f"    Eve shared the post")

        # --- Step 6: Stats ---
        await asyncio.sleep(0.5)
        print("\n[6] System stats:")
        db_stats = await db.get_stats()
        print(f"    Database:")
        print(f"      Users:       {db_stats['users']}")
        print(f"      Posts:       {db_stats['posts']}")
        print(f"      Friendships: {db_stats['friendships']}")
        print(f"      Actions:     {db_stats['actions']}")

        print(f"\n    Fanout:")
        fs = fanout.stats
        print(f"      Total fanouts:    {fs['total_fanouts']}")
        print(f"      Pull model skips: {fs['total_skipped_pull_model']}")
        print(f"      Queue pending:    {fs['queue_pending']}")

        print(f"\n    Cache layers:")
        cs = cache.stats
        for layer_name, layer_stats in cs.items():
            print(f"      {layer_name}: size={layer_stats['size']}, hit_rate={layer_stats['hit_rate']}")

        print("\n" + "=" * 60)
        print("  DEMO COMPLETE")
        print("=" * 60)

    finally:
        await fanout.stop()
        await db.close()


async def run_server():
    """Run the FastAPI server."""
    import uvicorn
    from app.server import app

    config = FeedConfig()
    print(f"Starting News Feed Server on {config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


def main():
    parser = argparse.ArgumentParser(description="News Feed System")
    parser.add_argument("--demo", action="store_true", help="Run demo")
    parser.add_argument("--server", action="store_true", help="Run API server")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.server:
        asyncio.run(run_server())
    else:
        asyncio.run(run_demo())


if __name__ == "__main__":
    main()
