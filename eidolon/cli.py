from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from eidolon.api.app import app
from eidolon.api.dependencies import get_scanner_store
from eidolon.collectors.factory import build_manager
from eidolon.core.graph.neo4j import Neo4jGraphRepository
from eidolon.core.models.scanner import ScannerConfig
from eidolon.core.reasoning.entity import EntityResolver
from eidolon.worker.ingest import IngestWorker


def _make_help_handler(parser: argparse.ArgumentParser):
    def _handler(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0

    return _handler


def _build_scan_config(config: ScannerConfig) -> dict:
    return {
        "network": {
            "cidrs": config.network_cidrs,
            "ping_concurrency": config.options.ping_concurrency,
            "port_scan_workers": config.options.port_scan_workers,
            "ports": config.ports,
            "port_preset": config.port_preset,
            "dns_resolution": config.options.dns_resolution,
            "aggressive": config.options.aggressive,
        }
    }


def cmd_scan(args: argparse.Namespace) -> int:
    store = get_scanner_store()
    record = store.get_config("cli-user")
    config = _build_scan_config(record.config)
    repository = Neo4jGraphRepository()
    try:
        resolver = EntityResolver()
        worker = IngestWorker(repository, resolver)

        event_count = 0

        def emit_fn(event) -> None:
            nonlocal event_count
            event_count += 1
            worker.process_event(event)

        manager = build_manager(config, emit_fn)
        collectors = manager.list_collectors()
        print(f"Starting network scan: {', '.join(collectors)}")

        errors = manager.run_all()

        print(f"Scan complete: {event_count} events ingested into Neo4j")

        if errors:
            print(f"Encountered {len(errors)} error(s):")
            for err in errors:
                print(f"  - {err}")
            return 1

        return 0
    finally:
        repository.close()


def cmd_db(args: argparse.Namespace) -> int:
    repository = Neo4jGraphRepository()
    try:
        if args.action == "stats":
            result = list(
                repository.run_cypher("MATCH (n) RETURN labels(n) as label, count(*) as count")
            )
            print("")
            print("Node counts by label:")
            total = 0
            for record in result:
                labels = record.get("label") or []
                count = record.get("count", 0)
                label_str = ":".join(labels) if labels else "(unlabeled)"
                print(f"  {label_str}: {count}")
                total += count
            print("")
            print(f"Total nodes: {total}")

            result = list(
                repository.run_cypher("MATCH ()-[r]->() RETURN type(r) as type, count(*) as count")
            )
            print("")
            print("Relationship counts by type:")
            rel_total = 0
            for record in result:
                print(f"  {record.get('type')}: {record.get('count')}")
                rel_total += record.get("count", 0)
            print("")
            print(f"Total relationships: {rel_total}")

        elif args.action == "clear":
            confirm = input(
                "WARNING: This will delete ALL data from Neo4j. Type 'yes' to confirm: "
            )
            if confirm.lower() == "yes":
                repository.clear()
                print("Database cleared")
            else:
                print("Cancelled")

        elif args.action == "query":
            if not args.cypher:
                print("cypher is required for db query")
                return 1
            result = list(repository.run_cypher(args.cypher))
            for record in result:
                print(json.dumps(dict(record), indent=2, default=str))
    finally:
        repository.close()
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eidolon", description="Eidolon CLI")

    # Default behavior: start the API server
    parser.add_argument(
        "--host", default="0.0.0.0", help="API server host (default: 0.0.0.0)"  # noqa: S104
    )
    parser.add_argument("--port", type=int, default=8080, help="API server port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload for development")
    parser.set_defaults(func=cmd_ui)

    sub = parser.add_subparsers(dest="command", required=False)

    help_cmd = sub.add_parser("help", help="Show help")
    help_cmd.set_defaults(func=_make_help_handler(parser))

    scan = sub.add_parser("scan", help="Run the network scan once")
    scan.set_defaults(func=cmd_scan)

    db_cmd = sub.add_parser("db", help="Database operations")
    db_cmd.add_argument("action", choices=["stats", "clear", "query"], help="Action to perform")
    db_cmd.add_argument("--cypher", help="Cypher query (for 'query' action)")
    db_cmd.set_defaults(func=cmd_db)

    ui = sub.add_parser("ui", help="Serve the web UI/API (alias for default behavior)")
    ui.add_argument("--host", default="0.0.0.0")  # noqa: S104
    ui.add_argument("--port", type=int, default=8080)
    ui.add_argument("--reload", action="store_true", help="Enable autoreload for development")
    ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
