"""Command-line interface: `solver ingest` and `solver preflop`."""

import argparse
import contextlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from solver import ingest, playbook, preflop, report, store
from solver.models import CheckStatus, DecisionCheck

HERO_ENV_VAR = "SOLVER_HERO"

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 2  # finished, but a hand failed to parse or a file was unreadable


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "preflop":
        return _run_preflop(args)
    return _run_ingest(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solver")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest", help="parse session files in a folder into the hand database"
    )
    ingest_parser.add_argument("folder", type=Path, help="folder of session files")
    ingest_parser.add_argument(
        "--hero", help=f"PokerStars username (default: ${HERO_ENV_VAR})"
    )
    ingest_parser.add_argument(
        "--db",
        type=Path,
        default=store.DEFAULT_DB_PATH,
        help="SQLite database path (default: %(default)s)",
    )

    preflop_parser = subparsers.add_parser(
        "preflop", help="check hero's first preflop decision against the playbook"
    )
    preflop_parser.add_argument(
        "--playbook",
        type=Path,
        default=playbook.DEFAULT_PLAYBOOK_PATH,
        help="playbook file (default: %(default)s)",
    )
    preflop_parser.add_argument(
        "--db",
        type=Path,
        default=store.DEFAULT_DB_PATH,
        help="SQLite database path (default: %(default)s)",
    )
    preflop_parser.add_argument("--session", help="exact session file basename")
    preflop_parser.add_argument(
        "--since", type=_parse_date, help="YYYY-MM-DD, inclusive"
    )
    preflop_parser.add_argument(
        "--until", type=_parse_date, help="YYYY-MM-DD, exclusive"
    )
    return parser


def _parse_date(text: str) -> datetime:
    try:
        # Midnight UTC: stored Hand.timestamp_utc values are tz-aware UTC.
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from None


def _run_ingest(args: argparse.Namespace) -> int:
    hero = args.hero or os.environ.get(HERO_ENV_VAR)
    if not hero:
        return _fatal(f"no hero name: pass --hero or set {HERO_ENV_VAR}")
    if not args.folder.is_dir():
        return _fatal(f"not a directory: {args.folder}")

    with contextlib.closing(store.connect(args.db)) as conn:
        results = ingest.ingest_folder(args.folder, hero, conn)
        if not results:
            return _fatal(
                f"no files matching {ingest.SESSION_FILE_PATTERN} in {args.folder}"
            )
        total_hands = store.count_hands(conn)

    _print_report(results, args.db, total_hands)
    has_problems = any(r.failed or r.read_error for r in results)
    return EXIT_PARTIAL if has_problems else EXIT_OK


def _fatal(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_FATAL


def _print_report(
    results: list[ingest.FileIngestResult], db_path: Path, total_hands: int
) -> None:
    for result in results:
        print(
            f"{result.source_file}  parsed {result.parsed:<2}  "
            f"new {result.inserted:<2}  updated {result.updated:<2}  "
            f"failed {len(result.failed)}"
        )

    for result in results:
        if result.read_error:
            print(
                f"  ERROR   {result.source_file} | "
                f"could not read file: {result.read_error}"
            )
        elif not result.parsed and not result.failed:
            print(f"  WARNING {result.source_file} | no hands found")
        for failed in result.failed:
            first_line = (failed.raw_text.splitlines() or [""])[0]
            error = " ".join(failed.error.split())
            print(f"  FAILED  {result.source_file} | {first_line} | {error}")

    print("---")
    print(
        f"Files: {len(results)}  "
        f"Parsed: {sum(r.parsed for r in results)}  "
        f"New: {sum(r.inserted for r in results)}  "
        f"Updated: {sum(r.updated for r in results)}  "
        f"Failed: {sum(len(r.failed) for r in results)}"
    )
    print(f"DB: {db_path} (total hands: {total_hands})")


def _run_preflop(args: argparse.Namespace) -> int:
    try:
        book = playbook.load_playbook(args.playbook)
    except playbook.PlaybookError as exc:
        return _fatal(f"invalid playbook {args.playbook}: {exc}")
    except (OSError, UnicodeDecodeError) as exc:
        return _fatal(f"cannot read playbook {args.playbook}: {exc}")

    with contextlib.closing(store.connect(args.db)) as conn:
        hands = store.load_hands(conn)
        if not hands:
            return _fatal(f"no hands in {args.db}; run `solver ingest` first")

        checks = []
        had_errors = False
        for hand in hands:
            try:
                checks.append(preflop.check_preflop(hand, book))
            except Exception as exc:  # noqa: BLE001 - one bad hand must not stop the run
                had_errors = True
                checks.append(
                    DecisionCheck(
                        hand_id=hand.hand_id,
                        status=CheckStatus.UNSUPPORTED,
                        reason=f"error: {exc!r}",
                    )
                )
        store.replace_preflop_checks(conn, checks, book.hash)
        selected = store.load_preflop_checks(
            conn, source_file=args.session, since=args.since, until=args.until
        )

    if args.session and not selected:
        return _fatal(f"no hands in session {args.session!r}")

    print(
        report.format_report(
            report.summarize(selected),
            scope=_scope(args),
            playbook_hash=book.hash,
            db_path=str(args.db),
        )
    )
    return EXIT_PARTIAL if had_errors else EXIT_OK


def _scope(args: argparse.Namespace) -> str:
    parts = [args.session] if args.session else []
    if args.since:
        parts.append(f"since {args.since:%Y-%m-%d}")
    if args.until:
        parts.append(f"until {args.until:%Y-%m-%d}")
    return " ".join(parts) or "all hands"
