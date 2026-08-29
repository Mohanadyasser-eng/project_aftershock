#!/usr/bin/env python3
"""
generate_aftershock_log.py — Project Aftershock synthetic log generator.

Builds a deliberately messy data/raw/regional_sensor_log.csv FROM a real list
of earthquake event ids (pulled live by the student from the USGS Earthquake
Catalog), instead of shipping a static pre-made file. Because the log is
generated from whatever ids the student actually pulled, a real join will
always have real matches — but three flaws are injected on every run so a
naive 1:1 join still fails:

    1. Dropped ids  (~10% of the input ids are simply missing from the log,
                      simulating sensor downtime)
    2. Ghost ids    (~10% extra, fabricated ids appear in the log that were
                      never in the input, simulating unrelated network noise)
    3. Dirty values (station_network's own choice list includes a whitespace/
                      tab-padded entry; local_claims_filed occasionally comes
                      back blank, whitespace-padded, "0", "N/A", or "null")

Usage (terminal):
    python generate_aftershock_log.py --input-ids extracted_ids.txt
    python generate_aftershock_log.py --input-ids extracted_ids.txt --output data/raw/regional_sensor_log.csv --seed 7
    python generate_aftershock_log.py                       # no file yet -> runs a built-in smoke test

Usage (notebook / direct import):
    from generate_aftershock_log import generate_aftershock_log
    generate_aftershock_log(my_event_id_list)
"""

import argparse
import csv
import random
from pathlib import Path

DEFAULT_OUTPUT = Path("data/raw/regional_sensor_log.csv")
FIELDNAMES = ["event_id", "station_network", "local_claims_filed"]

STATION_NETWORKS = ["PNSN-07", "CEA-12", "USGS-WEST", "SCEDC-01", " PNSN-07\t"]

DROP_RATE = 0.10
GHOST_RATE = 0.10
DIRTY_RATE = 0.15

# Real, live-verified USGS event ids so the script produces a genuine-looking
# file even with zero setup.
FALLBACK_IDS = [
    "uw714067081", "us7000py0f", "uw62242312", "ak0257jjjpjt", "uw62216847",
    "uw62197602", "uw62064837", "uw61976681", "ak024k7m66d", "uw61960946",
]


def _dirty_claims_filed():
    """Mostly a clean small integer string; occasionally blank, padded, '0', 'N/A', or 'null'."""
    clean_val = random.randint(0, 15)
    if random.random() < DIRTY_RATE:
        return random.choice(["", "N/A", "null", "0", f" {clean_val} "])
    return str(clean_val)


def _fabricate_ghost_id(used_ids):
    """Build a plausible USGS-shaped event id string that is not already in use."""
    prefixes = ["uw", "us", "ak", "nn", "ci", "nc"]
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        prefix = random.choice(prefixes)
        suffix = "".join(random.choice(alphabet) for _ in range(random.choice([8, 9, 10])))
        candidate = f"{prefix}{suffix}"
        if candidate not in used_ids:
            return candidate


def generate_aftershock_log(id_list, output_path=None, seed=None):
    """
    Write a messy regional_sensor_log.csv built from a real list of earthquake event ids.

    Args:
        id_list: iterable of event id strings (the API's top-level `id` field).
        output_path: where to write the CSV. Defaults to data/raw/regional_sensor_log.csv;
            parent folders are created automatically if they don't exist.
        seed: optional int for reproducible output (useful for grading/debugging).
            Leave as None for a fresh random log on every run.

    Returns:
        pathlib.Path to the file that was written.
    """
    if seed is not None:
        random.seed(seed)

    output_path = Path(output_path) if output_path else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ids = [str(i).strip() for i in id_list if str(i).strip()]

    n_drop = round(len(ids) * DROP_RATE)
    dropped = set(random.sample(ids, n_drop)) if n_drop else set()
    surviving_ids = [i for i in ids if i not in dropped]

    n_ghost = round(len(ids) * GHOST_RATE)
    used_ids = set(ids)
    ghost_ids = []
    for _ in range(n_ghost):
        ghost = _fabricate_ghost_id(used_ids)
        used_ids.add(ghost)
        ghost_ids.append(ghost)

    all_ids = surviving_ids + ghost_ids
    random.shuffle(all_ids)

    rows = [
        {
            "event_id": event_id,
            "station_network": random.choice(STATION_NETWORKS),
            "local_claims_filed": _dirty_claims_filed(),
        }
        for event_id in all_ids
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"[generate_aftershock_log] {len(ids)} input ids -> {len(rows)} log rows "
        f"({len(dropped)} dropped, {len(ghost_ids)} ghost ids injected) -> {output_path}"
    )
    return output_path


def _load_ids_from_file(path):
    """Read one id per line from a plain text file, ignoring blank lines."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Could not find {p}. Pass a text file with one event id per line via "
            "--input-ids, or omit --input-ids to run the built-in smoke test."
        )
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _cli():
    parser = argparse.ArgumentParser(
        description="Generate a messy data/raw/regional_sensor_log.csv for Project Aftershock."
    )
    parser.add_argument(
        "--input-ids", default=None,
        help="Path to a text file with one earthquake event id per line. Omit to run a built-in smoke test.",
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help=f"Output CSV path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Optional random seed for reproducible output.",
    )
    args = parser.parse_args()

    if args.input_ids:
        ids = _load_ids_from_file(args.input_ids)
    else:
        print("No --input-ids given; running with the built-in fallback id list as a smoke test.")
        ids = FALLBACK_IDS

    generate_aftershock_log(ids, output_path=args.output, seed=args.seed)


if __name__ == "__main__":
    _cli()
