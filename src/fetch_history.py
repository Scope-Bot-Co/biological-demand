#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from whoop_auth import get_valid_access_token
from fetch_data import (
    build_day,
    flatten_day,
    get_data,
    save_daily_row,
    save_raw_day,
)


def history_window(years: int = 2) -> tuple[str, str]:
    now = datetime.now().astimezone()
    start = now - timedelta(days=365 * years)
    return (
        start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def get_all(access_token: str, path: str, start: str, end: str) -> list[dict]:
    records: list[dict] = []
    next_token = None
    page = 0
    while True:
        query = {"start": start, "end": end, "limit": 25}
        if next_token:
            query["nextToken"] = next_token
        payload = get_data(access_token, path, query)
        batch = payload.get("records") or []
        records.extend(batch)
        page += 1
        print(f"{path} page {page}: +{len(batch)}  total={len(records)}")
        next_token = payload.get("next_token") or payload.get("nextToken")
        if not next_token:
            break
        time.sleep(0.2)
    return records


def local_date(iso_value: str | None) -> str | None:
    if not iso_value:
        return None
    dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    return dt.astimezone().date().isoformat()


def main() -> int:
    start, end = history_window(years=2)
    print(f"history window: {start} -> {end}")
    token = get_valid_access_token()

    recoveries = get_all(token, "/v2/recovery", start, end)
    cycles = get_all(token, "/v2/cycle", start, end)
    sleeps = get_all(token, "/v2/activity/sleep", start, end)
    workouts = get_all(token, "/v2/activity/workout", start, end)

    cycles_by_id = {cycle.get("id"): cycle for cycle in cycles}
    sleeps_by_id = {sleep.get("id"): sleep for sleep in sleeps}

    saved = 0
    for recovery in recoveries:
        cycle = cycles_by_id.get(recovery.get("cycle_id"))
        sleep = sleeps_by_id.get(recovery.get("sleep_id"))
        date = local_date((cycle or {}).get("start")) or local_date(recovery.get("created_at"))
        if not date:
            continue

        day_workouts = []
        if cycle and cycle.get("start") and cycle.get("end"):
            cycle_start = cycle["start"]
            cycle_end = cycle["end"]
            for workout in workouts:
                workout_start = workout.get("start") or ""
                if cycle_start <= workout_start < cycle_end:
                    day_workouts.append(workout)

        day = build_day(date, recovery, cycle, sleep, day_workouts)
        save_raw_day(day)
        save_daily_row(flatten_day(day))
        saved += 1

    print(f"saved {saved} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())