#!/usr/bin/env python3
from __future__ import annotations

import json
import csv
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from whoop_auth import TOKEN_PATH, get_valid_access_token


API_BASE = "https://api.prod.whoop.com/developer"

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DAILY_CSV = ROOT / "data" / "processed" / "daily.csv"

# calculates previous day time range in UTC -> returns start time, end time, and date
def yesterday_window() -> tuple[str, str, str]:
    now_local = datetime.now().astimezone()
    yesterday = now_local.date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time(), tzinfo=now_local.tzinfo)
    end = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=now_local.tzinfo)
    return (
        start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        yesterday.isoformat(),
    )

# reuseable data fetch for recovery, cycle, sleep, and workouts
# build URL with path -> GET request using access token -> recive record list
def get_data(access_token: str, path: str, query: dict | None = None) -> dict:   
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "whoop-demand/0.1",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Recovery request failed ({exc.code}): {detail}") from exc
    return payload

# recovery data fetch
def get_recoveries(access_token: str, start: str, end: str) -> list[dict]:
    payload = get_data(
        access_token,
        "/v2/recovery",
        {"start": start, "end": end, "limit": 10}
    )
    return payload.get("records", [])

# cycle data fetch
def get_cycle(access_token: str, cycle_id: int | str) -> dict:
    return get_data(access_token, f"/v2/cycle/{cycle_id}")

# sleep data fetch
def get_sleep(access_token: str, sleep_id: str) -> dict:
    return get_data(access_token, f"/v2/activity/sleep/{sleep_id}")

# workout data fetch
def get_workouts(access_token: str, start: str, end: str) -> list[dict]:
    payload = get_data(
        access_token,
        "/v2/activity/workout",
        {"start": start, "end": end, "limit": 25},
    )
    return payload.get("records", [])

# convert WHOOP sleep time from ms to hrs
def ms_to_hr(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{int(value) / 3_600_000:.2f}h"

def hr_from_ms(value: object) -> float | None:
    if value is None:
        return None
    return round(int(value) / 3_600_000, 2)

# reformat WHOOP recovery obj 
def summarize_recovery(record: dict) -> str:
    score = record.get("score") or {}
    return (
        f"created_at:       {record.get('created_at')}\n"
        f"score_state:      {record.get('score_state')}\n"
        f"recovery_score:   {score.get('recovery_score')}\n"
        f"resting_hr:       {score.get('resting_heart_rate')}\n"
        f"hrv_rmssd_milli:  {score.get('hrv_rmssd_milli')}\n"
        f"spo2_percentage:  {score.get('spo2_percentage')}\n"
        f"skin_temp_celsius:{score.get('skin_temp_celsius')}\n"
        f"cycle_id:         {record.get('cycle_id')}\n"
        f"sleep_id:         {record.get('sleep_id')}"
    )

# reformat WHOOP cycle obj 
def summarize_cycle(record: dict) -> str:
    score = record.get("score") or {}
    return (
        f"start:            {record.get('start')}\n"
        f"end:              {record.get('end')}\n"
        f"score_state:      {record.get('score_state')}\n"
        f"strain:           {score.get('strain')}\n"
        f"kilojoule:        {score.get('kilojoule')}\n"
        f"avg_hr:           {score.get('average_heart_rate')}\n"
        f"max_hr:           {score.get('max_heart_rate')}"
    )

# reformat WHOOP sleep obj 
def summarize_sleep(record: dict) -> str:
    score = record.get("score") or {}
    stages = score.get("stage_summary") or {}
    return (
        f"start:            {record.get('start')}\n"
        f"end:              {record.get('end')}\n"
        f"nap:              {record.get('nap')}\n"
        f"score_state:      {record.get('score_state')}\n"
        f"performance:      {score.get('sleep_performance_percentage')}\n"
        f"consistency:      {score.get('sleep_consistency_percentage')}\n"
        f"efficiency:       {score.get('sleep_efficiency_percentage')}\n"
        f"respiratory_rate: {score.get('respiratory_rate')}\n"
        f"in_bed:           {ms_to_hr(stages.get('total_in_bed_time_milli'))}\n"
        f"light:            {ms_to_hr(stages.get('total_light_sleep_time_milli'))}\n"
        f"sws:              {ms_to_hr(stages.get('total_slow_wave_sleep_time_milli'))}\n"
        f"rem:              {ms_to_hr(stages.get('total_rem_sleep_time_milli'))}\n"
        f"awake:            {ms_to_hr(stages.get('total_awake_time_milli'))}\n"
        f"disturbances:     {stages.get('disturbance_count')}"
    )

# reformat WHOOP workout obj 
def summarize_workout(record: dict) -> str:
    score = record.get("score") or {}
    return (
        f"  sport_id: {record.get('sport_id')}  "
        f"strain: {score.get('strain')}  "
        f"avg_hr: {score.get('average_heart_rate')}  "
        f"start: {record.get('start')}"
    )

def build_day(date: str, recovery: dict, cycle: dict | None, sleep: dict | None, workouts: list[dict]) -> dict:
    return {
        "date": date,
        "recovery": recovery,
        "cycle": cycle,
        "sleep": sleep,
        "workouts": workouts,
    }


def save_raw_day(day: dict) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{day['date']}.json"
    path.write_text(json.dumps(day, indent=2) + "\n")
    return path


def flatten_day(day: dict) -> dict:
    recovery = day.get("recovery") or {}
    cycle = day.get("cycle") or {}
    sleep = day.get("sleep") or {}
    workouts = day.get("workouts") or []

    recovery_score = recovery.get("score") or {}
    cycle_score = cycle.get("score") or {}
    sleep_score = sleep.get("score") or {}
    stages = sleep_score.get("stage_summary") or {}

    workout_strain = 0.0
    for workout in workouts:
        score = workout.get("score") or {}
        if score.get("strain") is not None:
            workout_strain += float(score["strain"])

    return {
        "date": day.get("date"),
        "recovery_score": recovery_score.get("recovery_score"),
        "hrv_rmssd_milli": recovery_score.get("hrv_rmssd_milli"),
        "resting_hr": recovery_score.get("resting_heart_rate"),
        "spo2_percentage": recovery_score.get("spo2_percentage"),
        "skin_temp_celsius": recovery_score.get("skin_temp_celsius"),
        "strain": cycle_score.get("strain"),
        "sleep_performance": sleep_score.get("sleep_performance_percentage"),
        "sleep_hours": hr_from_ms(stages.get("total_in_bed_time_milli")),
        "workout_count": len(workouts),
        "workout_strain": round(workout_strain, 2),
    }


def save_daily_row(row: dict) -> Path:
    DAILY_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(row.keys())

    rows = []
    if DAILY_CSV.exists():
        with DAILY_CSV.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

    rows = [existing for existing in rows if existing.get("date") != row["date"]]
    rows.append({name: row.get(name) for name in fieldnames})
    rows.sort(key=lambda item: item.get("date") or "")

    with DAILY_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return DAILY_CSV

def main() -> int:
    print("token file:", TOKEN_PATH)
    access_token = get_valid_access_token()
    start, end, yesterday = yesterday_window()
    print(f"window: {start} -> {end}")
    print(f"date: {yesterday}")

    records = get_recoveries(access_token, start, end)
    if not records:
        print("No recovery records in that window.")
        return 0

    recovery = records[0]
    print("\n--- recovery ---")
    print(summarize_recovery(recovery))

    cycle_id = recovery.get("cycle_id")
    sleep_id = recovery.get("sleep_id")

    cycle = None
    sleep = None
    workouts = []

    if cycle_id is None:
        print("\nNo cycle_id on this recovery; skipping cycle + workouts.")
    else:
        cycle = get_cycle(access_token, cycle_id)
        print("\n--- cycle / strain ---")
        print(summarize_cycle(cycle))

    if not sleep_id:
        print("\nNo sleep_id on this recovery; skipping sleep.")
    else:
        sleep = get_sleep(access_token, sleep_id)
        print("\n--- sleep ---")
        print(summarize_sleep(sleep))

    if cycle and cycle.get("start") and cycle.get("end"):
        workouts = get_workouts(access_token, cycle["start"], cycle["end"])
        print(f"\n--- workouts ({len(workouts)}) ---")
        if not workouts:
            print("No workouts in this cycle.")
        else:
            for workout in workouts:
                print(summarize_workout(workout))

    day = build_day(yesterday, recovery, cycle, sleep, workouts)
    raw_path = save_raw_day(day)
    csv_path = save_daily_row(flatten_day(day))
    print(f"\nsaved raw: {raw_path}")
    print(f"saved row: {csv_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())