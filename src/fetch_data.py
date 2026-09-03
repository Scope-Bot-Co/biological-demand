#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from whoop_auth import TOKEN_PATH, get_valid_access_token


API_BASE = "https://api.prod.whoop.com/developer"

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


def main() -> int:
    print("token file:", TOKEN_PATH)
    access_token = get_valid_access_token() # get access token -> whoop_auth.py
    start, end, yesterday = yesterday_window() # calculate previous day window -> start, end, date
    print(f"window: {start} -> {end}")
    print(f"date: {yesterday}")

    records = get_recoveries(access_token, start, end) # get data from WHOOP -> recovery data
    if not records:
        print("No recovery records in that window.")
        return 0

    recovery = records[0]
    print("\n--- recovery ---")
    print(summarize_recovery(recovery))

    cycle_id = recovery.get("cycle_id")
    sleep_id = recovery.get("sleep_id")

    cycle = None
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

        return 0


if __name__ == "__main__":
    sys.exit(main())