"""
CLI entry point for the Search Autocomplete System.

Usage:
    python -m search-autocomplete              # Start API server
    python search-autocomplete/__main__.py     # Alternative way to start
"""
import argparse
import logging
import sys

import uvicorn

from app.config import config


def main():
    parser = argparse.ArgumentParser(
        description="Search Autocomplete System - Trie-based autocomplete with top-k caching"
    )
    parser.add_argument(
        "--host",
        default=config.host,
        help=f"Host to bind (default: {config.host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.port,
        help=f"Port to bind (default: {config.port})",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Starting Search Autocomplete System on {args.host}:{args.port}")

    uvicorn.run(
        "app.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main()
