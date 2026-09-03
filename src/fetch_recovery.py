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

# build URL with start + end + date -> GET request using access token -> recive record list
def get_recoveries(access_token: str, start: str, end: str) -> list[dict]:
    query = urllib.parse.urlencode({"start": start, "end": end, "limit": 10})
    url = f"{API_BASE}/v2/recovery?{query}"
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
    return payload.get("records", [])

# reformat WHOOP recovery obj 
def summarize(record: dict) -> str:
    score = record.get("score") or {}
    return (
        f"created_at:       {record.get('created_at')}\n"
        f"score_state:      {record.get('score_state')}\n"
        f"recovery_score:   {score.get('recovery_score')}\n"
        f"resting_hr:       {score.get('resting_heart_rate')}\n"
        f"hrv_rmssd_milli:  {score.get('hrv_rmssd_milli')}\n"
        f"spo2_percentage:  {score.get('spo2_percentage')}\n"
        f"skin_temp_celsius:{score.get('skin_temp_celsius')}\n"
        f"cycle_id:         {record.get('cycle_id')}"
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

    print(summarize(records[0])) # reformatted WHOOP data
    return 0


if __name__ == "__main__":
    sys.exit(main())