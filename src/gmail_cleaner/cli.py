"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .agent import DEFAULT_MODEL, run
from .auth import get_service
from .cleanup import trash_senders
from .gmail import Gmail
from .session import Session


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="gmail-cleaner", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run the cleanup agent (dry-run unless --apply)")
    r.add_argument("--apply", action="store_true", help="Actually modify the mailbox")
    r.add_argument("--config", type=Path, help="YAML config (see examples/config.example.yaml)")
    r.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    r.add_argument("--token", type=Path, default=Path("token.json"))
    r.add_argument("--log", type=Path, default=Path("actions.jsonl"))
    r.add_argument("--max-actions", type=int, help="Override config max_actions")
    r.add_argument("--model", help="Override config model")

    d = sub.add_parser("delete", help="Move all mail from given senders to Trash (no LLM)")
    d.add_argument("senders", nargs="*", help="Sender addresses or domains, e.g. news@shop.com")
    d.add_argument("--from-file", type=Path, help="Text file with one sender per line")
    d.add_argument("--apply", action="store_true", help="Actually move mail to Trash")
    d.add_argument("--limit", type=int, help="Max messages per sender")
    d.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    d.add_argument("--token", type=Path, default=Path("token.json"))
    d.add_argument("--log", type=Path, default=Path("actions.jsonl"))

    args = p.parse_args(argv)
    if args.cmd == "delete":
        return _delete(args)
    cfg = yaml.safe_load(args.config.read_text()) if args.config else {}

    session = Session(
        gmail=Gmail(get_service(args.credentials, args.token)),
        apply=args.apply,
        max_actions=args.max_actions or cfg.get("max_actions", 200),
        protected_senders=cfg.get("protected_senders", []),
        log_path=args.log,
    )
    summary = run(
        session,
        instructions=cfg.get("instructions", ""),
        model=args.model or cfg.get("model", DEFAULT_MODEL),
    )
    print(summary)
    verb = "Modified" if args.apply else "Would modify"
    print(f"\n{verb} {session.actions_taken} message(s). Log: {args.log}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to make changes.")


def _delete(args) -> None:
    senders = list(args.senders)
    if args.from_file:
        senders += [
            line.strip()
            for line in args.from_file.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    if not senders:
        raise SystemExit("Give at least one sender, or --from-file.")

    gmail = Gmail(get_service(args.credentials, args.token))
    results = trash_senders(gmail, senders, args.apply, args.limit, args.log)
    for r in results:
        print(f"{r.sender}: {r.count} message(s)")
        for s in r.samples:
            print(f"    e.g. {s}")
    total = sum(r.count for r in results)
    if args.apply:
        print(f"\nMoved {total} message(s) to Trash (recoverable for 30 days). Log: {args.log}")
    else:
        print(f"\nWould move {total} message(s) to Trash. Re-run with --apply to do it.")


if __name__ == "__main__":
    main()
