"""Command-line entrypoint for gaming-mcp server."""

import argparse
import asyncio
import sys

from gaming_mcp.config import GamingMCPConfig, TransportType
from gaming_mcp.utils.logging import setup_logging


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="gaming-mcp",
        description="Sovereign Model Context Protocol (MCP) server for video games",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON configuration file",
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http", "sse"],
        default=None,
        help="Server transport type (stdio, http, sse)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address for HTTP/SSE transport",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port number for HTTP/SSE transport",
    )
    parser.add_argument(
        "--adapter",
        type=str,
        default=None,
        help="Initial game adapter to activate",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging level",
    )
    return parser.parse_args(args)


async def async_main(config: GamingMCPConfig) -> None:
    """Async main routine."""
    from gaming_mcp.server import GamingMCPServer

    logger = setup_logging(config.log_level)
    logger.info(
        "Initializing gaming-mcp server",
        extra={
            "transport": config.transport.value,
            "adapter": config.adapters.default_adapter,
        },
    )
    server = GamingMCPServer(config)
    await server.start()


def main() -> None:
    """CLI execution entry point."""
    args = parse_args()
    config = GamingMCPConfig.load(args.config)

    if args.transport:
        config.transport = TransportType(args.transport)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.adapter:
        config.adapters.default_adapter = args.adapter
    if args.log_level:
        config.log_level = args.log_level

    try:
        asyncio.run(async_main(config))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
