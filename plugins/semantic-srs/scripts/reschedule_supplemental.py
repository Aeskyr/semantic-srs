from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay active cards under the supplemental scheduling policy."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes transactionally; otherwise perform a dry run.",
    )
    args = parser.parse_args()
    print(json.dumps(server.reschedule_supplemental_policy(apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
