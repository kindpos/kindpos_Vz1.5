"""Entry point for `python -m kindnostic`."""

import argparse
import sys

from kindnostic.runner import run_all, run_single_probe


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="kindnostic",
        description="KINDnostic — Boot Diagnostic System for KINDpos",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed probe metadata in output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON (machine-readable)",
    )
    parser.add_argument(
        "--probe",
        type=str,
        default=None,
        help="Run a single probe by name (e.g. --probe hash_chain_integrity)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to diagnostic_boot.db (overrides default)",
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Start boot display HTTP server on port 8888 for kiosk browser",
    )

    args = parser.parse_args()

    if args.probe:
        return run_single_probe(
            probe_name=args.probe,
            db_path=args.db_path,
            verbose=args.verbose,
            json_output=args.json_output,
        )

    return run_all(
        db_path=args.db_path,
        verbose=args.verbose,
        json_output=args.json_output,
        display=args.display,
    )


sys.exit(main())
