"""Project Aftershock end-to-end pipeline: fetch, clean, engineer, join, scale."""

import csv
import json
import sys
from pathlib import Path

import requests

SRC_DIR = Path(__file__).resolve().parent
REPO_ROOT = SRC_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from generate_aftershock_log import generate_aftershock_log

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
SENSOR_LOG_PATH = RAW_DIR / "regional_sensor_log.csv"
EXTRACTED_IDS_PATH = RAW_DIR / "extracted_ids.txt"
CLEAN_DATA_PATH = PROCESSED_DIR / "clean_data.csv"

SIGNIFICANT_THRESHOLD = 5.0

CLEAN_FIELDNAMES = [
    "event_id",
    "mag",
    "scaled_mag",
    "depth_km",
    "depth_category",
    "felt",
    "gap",
    "sig",
    "significant",
    "region",
    "station_network",
    "local_claims_filed",
]


def fetch_earthquake_data(start_date, end_date, min_magnitude=2.5):
    """Pull the USGS FDSN event catalog for the given window, or return None on failure."""
    params = {
        "format": "geojson",
        "starttime": start_date,
        "endtime": end_date,
        "minmagnitude": min_magnitude,
    }
    try:
        response = requests.get(USGS_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        return payload.get("features", [])
    except requests.exceptions.RequestException as exc:
        print(f"USGS API request failed: {exc}")
        return None


def extract_event_ids(records):
    """Return the list of top-level event ids from a list of GeoJSON features."""
    return [record["id"] for record in records if record.get("id")]


def save_extracted_ids(event_ids, path=EXTRACTED_IDS_PATH):
    """Write one event id per line to a text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(event_ids), encoding="utf-8")
    return path


def load_sensor_log(path=SENSOR_LOG_PATH):
    """Load the regional sensor log CSV into a dict keyed by event_id."""
    sensor_dict = {}
    try:
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sensor_dict[row["event_id"]] = row
    except FileNotFoundError:
        print(f"Sensor log not found at {path}; joins will use defaults for every record.")
    return sensor_dict


def compute_median(values):
    """Compute the median of a list of numeric values using a sort, no statistics library."""
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 0:
        return (ordered[mid - 1] + ordered[mid]) / 2
    return ordered[mid]


def compute_medians(records):
    """Compute median gap, dmin, and nst across earthquake-type records with non-null values."""
    gaps, dmins, nsts = [], [], []
    for record in records:
        props = record.get("properties", {})
        if props.get("type") != "earthquake":
            continue
        if props.get("gap") is not None:
            gaps.append(props["gap"])
        if props.get("dmin") is not None:
            dmins.append(props["dmin"])
        if props.get("nst") is not None:
            nsts.append(props["nst"])
    return {
        "gap": compute_median(gaps),
        "dmin": compute_median(dmins),
        "nst": compute_median(nsts),
    }


def categorize_depth(depth_km):
    """Bucket a depth in km into shallow / intermediate / deep."""
    if depth_km < 70:
        return "shallow"
    if depth_km <= 300:
        return "intermediate"
    return "deep"


def clean_and_engineer(records, sensor_dict, medians):
    """Filter to earthquakes, impute, engineer features, and join sensor log data."""
    clean_records = []
    for record in records:
        props = record.get("properties", {})
        geom = record.get("geometry", {})
        coords = geom.get("coordinates", [])

        if props.get("type") != "earthquake":
            continue

        mag = props.get("mag")
        if mag is None:
            continue

        place = props.get("place") or ""
        if " of " in place:
            region = place.split(" of ")[1]
        else:
            region = place

        depth_km = coords[2] if len(coords) > 2 and coords[2] is not None else 0.0
        depth_category = categorize_depth(depth_km)

        felt = props.get("felt")
        if felt is None:
            felt = 0

        gap = props.get("gap")
        if gap is None:
            gap = medians["gap"]

        sig = props.get("sig")
        if sig is None:
            sig = 0

        significant = 1 if mag >= SIGNIFICANT_THRESHOLD else 0

        event_id = record["id"]
        log_row = sensor_dict.get(event_id)
        if log_row:
            station_network = (log_row.get("station_network") or "unknown").strip()
            raw_claims = (log_row.get("local_claims_filed") or "").strip()
            local_claims_filed = raw_claims if raw_claims.isdigit() else "0"
        else:
            station_network = "unknown"
            local_claims_filed = "0"

        clean_records.append({
            "event_id": event_id,
            "mag": mag,
            "depth_km": depth_km,
            "depth_category": depth_category,
            "felt": felt,
            "gap": gap,
            "sig": sig,
            "significant": significant,
            "region": region,
            "station_network": station_network,
            "local_claims_filed": local_claims_filed,
        })

    return clean_records


def scale_magnitudes(clean_records):
    """Add a min-max scaled_mag column in place, returning the same list."""
    if not clean_records:
        return clean_records
    mags = [row["mag"] for row in clean_records]
    min_mag, max_mag = min(mags), max(mags)
    span = max_mag - min_mag
    for row in clean_records:
        row["scaled_mag"] = (row["mag"] - min_mag) / span if span > 0 else 0.0
    return clean_records


def compute_validation_metrics(clean_records):
    """Compare average sig for significant vs non-significant records, plus ROI figures."""
    sig_1 = [r["sig"] for r in clean_records if r["significant"] == 1]
    sig_0 = [r["sig"] for r in clean_records if r["significant"] == 0]
    avg_sig_1 = sum(sig_1) / len(sig_1) if sig_1 else 0.0
    avg_sig_0 = sum(sig_0) / len(sig_0) if sig_0 else 0.0

    n_total = len(clean_records)
    n_flagged = len(sig_1)
    workload_reduction = (1 - (n_flagged / n_total)) * 100 if n_total > 0 else 0.0

    return {
        "avg_sig_significant": avg_sig_1,
        "avg_sig_not_significant": avg_sig_0,
        "n_total": n_total,
        "n_flagged": n_flagged,
        "pct_workload_reduction": workload_reduction,
    }


def write_clean_csv(clean_records, path=CLEAN_DATA_PATH):
    """Write the cleaned, engineered, joined, scaled records to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CLEAN_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clean_records)
    return path


def run_pipeline(start_date="2026-07-01", end_date="2026-08-01", min_magnitude=2.5):
    """Run the full Aftershock pipeline end to end and return the validation metrics."""
    records = fetch_earthquake_data(start_date, end_date, min_magnitude)
    if records is None:
        print("Aborting pipeline: could not retrieve USGS data.")
        return None

    print(f"Fetched {len(records)} raw records from USGS.")

    event_ids = extract_event_ids(records)
    save_extracted_ids(event_ids)
    print(f"Extracted {len(event_ids)} event ids to {EXTRACTED_IDS_PATH}.")

    generate_aftershock_log(event_ids, output_path=SENSOR_LOG_PATH)
    sensor_dict = load_sensor_log(SENSOR_LOG_PATH)

    medians = compute_medians(records)
    clean_records = clean_and_engineer(records, sensor_dict, medians)
    clean_records = scale_magnitudes(clean_records)

    metrics = compute_validation_metrics(clean_records)
    write_clean_csv(clean_records, CLEAN_DATA_PATH)

    print(f"Wrote {len(clean_records)} cleaned records to {CLEAN_DATA_PATH}.")
    print(
        f"Validation: avg sig (significant=1) = {metrics['avg_sig_significant']:.2f}, "
        f"avg sig (significant=0) = {metrics['avg_sig_not_significant']:.2f}"
    )
    print(
        f"ROI: n_total={metrics['n_total']}, n_flagged={metrics['n_flagged']}, "
        f"workload_reduction={metrics['pct_workload_reduction']:.2f}%"
    )

    return metrics


if __name__ == "__main__":
    run_pipeline()
