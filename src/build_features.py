#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAILY_CSV = ROOT / "data" / "processed" / "daily.csv"
FEATURES_CSV = ROOT / "data" / "processed" / "features.csv"

NUMERIC = [
    "recovery_score",
    "hrv_rmssd_milli",
    "resting_hr",
    "spo2_percentage",
    "skin_temp_celsius",
    "strain",
    "sleep_performance",
    "sleep_hours",
    "workout_count",
    "workout_strain",
]


def to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def mean(values: list[float | None]) -> float | None:
    nums = [value for value in values if value is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def rolling_before(series: list[float | None], index: int, window: int = 7) -> float | None:
    start = max(0, index - window)
    return mean(series[start:index])


def round_or_none(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def main() -> int:
    if not DAILY_CSV.exists():
        print(f"missing {DAILY_CSV}")
        return 1

    with DAILY_CSV.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    rows.sort(key=lambda row: row.get("date") or "")

    parsed = []
    for row in rows:
        item = {"date": row.get("date")}
        for name in NUMERIC:
            item[name] = to_float(row.get(name))
        parsed.append(item)

    hrv = [row["hrv_rmssd_milli"] for row in parsed]
    rhr = [row["resting_hr"] for row in parsed]
    sleep_hours = [row["sleep_hours"] for row in parsed]
    sleep_perf = [row["sleep_performance"] for row in parsed]
    strain = [row["strain"] for row in parsed]
    workout_strain = [row["workout_strain"] for row in parsed]
    spo2 = [row["spo2_percentage"] for row in parsed]
    temp = [row["skin_temp_celsius"] for row in parsed]

    features = []
    for i, row in enumerate(parsed):
        hrv_7d = rolling_before(hrv, i)
        rhr_7d = rolling_before(rhr, i)
        sleep_7d = rolling_before(sleep_hours, i)
        sleep_perf_7d = rolling_before(sleep_perf, i)
        strain_7d = rolling_before(strain, i)
        spo2_7d = rolling_before(spo2, i)
        temp_7d = rolling_before(temp, i)
        yesterday_strain = strain[i - 1] if i else None
        yesterday_workout_strain = workout_strain[i - 1] if i else None

        hrv_delta = None
        if row["hrv_rmssd_milli"] is not None and hrv_7d is not None:
            hrv_delta = row["hrv_rmssd_milli"] - hrv_7d

        rhr_delta = None
        if row["resting_hr"] is not None and rhr_7d is not None:
            rhr_delta = row["resting_hr"] - rhr_7d

        sleep_debt = None
        if row["sleep_hours"] is not None and sleep_7d is not None:
            sleep_debt = sleep_7d - row["sleep_hours"]

        features.append(
            {
                "date": row["date"],
                "recovery_score": row["recovery_score"],
                "strain": row["strain"],
                "workout_strain": row["workout_strain"],
                "workout_count": row["workout_count"],
                "sleep_hours": row["sleep_hours"],
                "sleep_performance": row["sleep_performance"],
                "hrv_rmssd_milli": row["hrv_rmssd_milli"],
                "resting_hr": row["resting_hr"],
                "spo2_percentage": row["spo2_percentage"],
                "skin_temp_celsius": row["skin_temp_celsius"],
                "hrv_7d": round_or_none(hrv_7d),
                "rhr_7d": round_or_none(rhr_7d),
                "sleep_hours_7d": round_or_none(sleep_7d),
                "sleep_performance_7d": round_or_none(sleep_perf_7d),
                "strain_7d": round_or_none(strain_7d),
                "spo2_7d": round_or_none(spo2_7d),
                "skin_temp_7d": round_or_none(temp_7d),
                "hrv_delta": round_or_none(hrv_delta),
                "rhr_delta": round_or_none(rhr_delta),
                "sleep_debt": round_or_none(sleep_debt),
                "yesterday_strain": yesterday_strain,
                "yesterday_workout_strain": yesterday_workout_strain,
            }
        )

    fieldnames = list(features[0].keys())
    FEATURES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with FEATURES_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(features)

    print(f"wrote {len(features)} rows to {FEATURES_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())