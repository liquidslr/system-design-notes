"""
Notification System — CLI Entry Point & Demo

Usage:
    python -m notification_system                    # Run API server
    python -m notification_system --demo             # Run interactive demo
    python -m notification_system --server-only      # Run server only
"""
import argparse
import asyncio
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import NotificationConfig
from app.database import Database
from app.models import (
    DeviceToken, NotificationRequest, NotificationSettings,
    NotificationType, UserInfo,
)
from app.providers.providers import ProviderRegistry
from app.queue.message_queue import MessageQueue
from app.service import NotificationService
from app.templates import TemplateEngine
from app.workers import WorkerPool


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


async def run_demo():
    """Run a demonstration of the notification system."""
    print("=" * 60)
    print("  NOTIFICATION SYSTEM — DEMO")
    print("=" * 60)
    print()

    config = NotificationConfig(num_workers=3)
    db = Database(config)
    queue = MessageQueue()
    template_engine = TemplateEngine()
    providers = ProviderRegistry().create_default(config)
    service = NotificationService(config, db, queue, template_engine)
    workers = WorkerPool(config, db, queue, providers)

    await db.initialize()
    await workers.start()

    try:
        # --- Step 1: Register users ---
        print("[1] Registering users...")
        users = [
            UserInfo(user_id="user_1", email="alice@example.com", phone="+1234567890"),
            UserInfo(user_id="user_2", email="bob@example.com", phone="+0987654321"),
            UserInfo(user_id="user_3", email="charlie@example.com", phone="+1122334455"),
        ]
        for u in users:
            await db.upsert_user(u)
            print(f"    Registered: {u.user_id} ({u.email})")

        # Register devices for push
        print("\n[2] Registering devices...")
        devices = [
            DeviceToken(user_id="user_1", device_token="ios_token_abc123", platform="ios"),
            DeviceToken(user_id="user_1", device_token="android_token_def456", platform="android"),
            DeviceToken(user_id="user_2", device_token="ios_token_ghi789", platform="ios"),
        ]
        for d in devices:
            await db.register_device(d)
            print(f"    Device: {d.user_id} -> {d.platform} ({d.device_token[:20]}...)")

        # Set notification preferences
        print("\n[3] Setting notification preferences...")
        await db.upsert_settings(NotificationSettings(
            user_id="user_3", push_enabled=True, sms_enabled=False, email_enabled=True,
        ))
        print("    user_3: push=ON, sms=OFF, email=ON")

        # --- Step 2: Send various notifications ---
        print("\n[4] Sending notifications...")

        test_notifications = [
            # Template-based billing reminder
            NotificationRequest(
                user_id="user_1",
                event_type="billing_reminder",
                channel=NotificationType.EMAIL,
                template_id="billing_reminder_email",
                template_data={"user_name": "Alice", "amount": "29.99", "due_date": "2026-10-01"},
            ),
            # Template-based push notification
            NotificationRequest(
                user_id="user_1",
                event_type="shipping_update",
                channel=NotificationType.PUSH_IOS,
                template_id="shipping_update_push",
                template_data={"order_id": "ORD-12345", "status": "shipped", "tracking_url": "https://track.example.com/12345"},
            ),
            # SMS notification
            NotificationRequest(
                user_id="user_2",
                event_type="security_alert",
                channel=NotificationType.SMS,
                template_id="security_alert_sms",
                template_data={"message": "New login detected from Chrome on Windows"},
            ),
            # Raw email
            NotificationRequest(
                user_id="user_2",
                event_type="promotion",
                channel=NotificationType.EMAIL,
                title="Flash Sale!",
                body="50% off all items this weekend only!",
            ),
            # Android push
            NotificationRequest(
                user_id="user_1",
                event_type="price_drop",
                channel=NotificationType.PUSH_ANDROID,
                template_id="price_drop_push",
                template_data={"product_name": "Wireless Headphones", "new_price": "79.99", "old_price": "129.99"},
            ),
            # Opted-out test (user_3 has SMS disabled)
            NotificationRequest(
                user_id="user_3",
                event_type="system",
                channel=NotificationType.SMS,
                title="Test",
                body="This should be blocked",
            ),
            # Duplicate test
            NotificationRequest(
                user_id="user_1",
                event_type="system",
                channel=NotificationType.EMAIL,
                title="Duplicate Test",
                body="This is a duplicate",
                event_id="dedup-test-event-001",
            ),
            NotificationRequest(
                user_id="user_1",
                event_type="system",
                channel=NotificationType.EMAIL,
                title="Duplicate Test",
                body="This is a duplicate",
                event_id="dedup-test-event-001",  # Same event_id!
            ),
        ]

        for i, req in enumerate(test_notifications, 1):
            result = await service.process_request(req)
            status = result["status"]
            emoji = {"queued": "✓", "duplicate": "⊘", "opted_out": "⊘", "rejected": "✗"}.get(status, "?")
            print(f"    [{emoji}] #{i} {req.channel.value:14s} -> {req.user_id:8s} | {status}")

        # --- Step 3: Wait for workers to process ---
        print("\n[5] Waiting for workers to process queue...")
        await asyncio.sleep(3)

        # --- Step 4: Show results ---
        print("\n[6] Results:")
        db_stats = await db.get_stats()
        print(f"    Total notifications logged: {db_stats['total']}")
        print(f"    Sent:      {db_stats.get('sent', 0)}")
        print(f"    Failed:    {db_stats.get('failed', 0)}")
        print(f"    Queued:    {db_stats.get('queued', 0)}")
        print(f"    Duplicate: {db_stats.get('duplicate', 0)}")
        print(f"    Opted out: {db_stats.get('opted_out', 0)}")
        print(f"    Rate limited: {db_stats.get('rate_limited', 0)}")

        print(f"\n    Worker stats:")
        print(f"    Sent:     {workers.stats['total_sent']}")
        print(f"    Failed:   {workers.stats['total_failed']}")
        print(f"    Retried:  {workers.stats['total_retried']}")

        print(f"\n    Queue stats:")
        print(f"    Pending:  {queue.stats['pending']}")
        print(f"    Enqueued: {queue.stats['total_enqueued']}")
        print(f"    Dequeued: {queue.stats['total_dequeued']}")

        # Show logs
        print("\n[7] Notification logs:")
        logs = await db.get_logs(limit=10)
        for log in logs:
            status_icon = {"sent": "✓", "failed": "✗", "queued": "→", "duplicate": "⊘", "opted_out": "⊘"}.get(log["status"], "?")
            print(f"    [{status_icon}] {log['channel']:14s} | {log['user_id']:8s} | {log['status']:12s} | {log['body'][:40]}...")

        print("\n" + "=" * 60)
        print("  DEMO COMPLETE")
        print("=" * 60)

    finally:
        await workers.stop()
        await db.close()


async def run_server():
    """Run the FastAPI server."""
    import uvicorn
    from app.server import app

    config = NotificationConfig()
    print(f"Starting Notification Server on {config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


def main():
    parser = argparse.ArgumentParser(description="Notification System")
    parser.add_argument("--demo", action="store_true", help="Run interactive demo")
    parser.add_argument("--server", action="store_true", help="Run API server")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.demo:
        asyncio.run(run_demo())
    elif args.server:
        asyncio.run(run_server())
    else:
        # Default: run demo
        asyncio.run(run_demo())


if __name__ == "__main__":
    main()
