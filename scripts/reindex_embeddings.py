#!/usr/bin/env python3
"""Build or rebuild Ollama embeddings for all trained documents."""

from __future__ import annotations

import argparse
import json
import sys

from knowledge import reindex_all_embeddings


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex RoPac document embeddings")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when embeddings already exist",
    )
    args = parser.parse_args()

    result = reindex_all_embeddings(force=args.force)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
