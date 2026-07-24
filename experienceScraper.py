# Dumb script to scrape sailing data from MIT Sailing website
# Lucas Ehinger 12-Sep-24
# Known issues that I probably won't get around to fixing:
#       -- Counts trips that are not sails (bluewater work days)
#       -- Multi-day trips must be multi-day in the date (not description)

# There are better ways to organize this code, but I'm lazy and it runs quickly enough

import os
import pandas as pd
import re
from urllib.request import urlopen
from datetime import datetime


def get_trip_urls(year,month):
    url = f"http://sailing.mit.edu/calendar/index.php?cal=month&year={year}&month={month}&type=13"
    page = urlopen(url)

    html_bytes = page.read()
    html = html_bytes.decode("utf-8", errors='ignore')

    pattern = r"(/calendar/events/event[^']*')"
    matches = re.findall(pattern, html)

    base_url = "http://sailing.mit.edu"
    updated_matches = [base_url + match[:-1] for match in matches]

    # Replace event.php with entries.php
    updated_matches = [match.replace("event.php", "entries.php") for match in updated_matches]

    unique_matches = list(set(updated_matches))
    return unique_matches

def get_title(html):
    title = re.search(r'<title>(.*?)</title>', html)
    title = title.group(1)
    if title.endswith(" Entries"):
        title = title[:-8]
    return title

def is_cancelled(html):
    title = get_title(html)
    return "cancel" in title.lower()

def get_time_data(html):
    times = re.findall(r'<tr><td style=\'text-align:right\'>(.*?)</td></tr>', html)
    times = [time for time in times if "Registration" not in time]
    start = times[0].split("</td><td>")
    start_day=start[0].split(' ')[1]
    start_time=start[1].split('-')[0]
    end = times[-1].split("</td><td>")
    end_day=end[0].split(' ')[1]
    end_time=end[1].split('-')[1]

    date_format = "%d-%b-%Y %H:%M"
    start_datetime = datetime.strptime(f"{start_day} {start_time}", date_format)
    end_datetime = datetime.strptime(f"{end_day} {end_time}", date_format)

    time_difference = end_datetime - start_datetime
    hours_elapsed = time_difference.total_seconds() / 3600

    return start_datetime, end_datetime, hours_elapsed

def is_racing(html):
    url = re.search(r'/calendar/events/event.php([^"]*)\'>Description', html)
    if not url:
        return False
    url = base_url = "http://sailing.mit.edu/calendar/events/event.php"+ url.group(1)
    page = urlopen(url)
    html_bytes = page.read()
    html = html_bytes.decode("utf-8", errors='ignore')

    description = re.search(r'<h2>Description</h2>(.*?)<h2>Organizers</h2>', html, re.DOTALL)
    if not description:
        return False
    description=description.group(1).strip()

    keywords = ["race", "regatta", "cup"]
    text = description + get_title(html)
    lower_text = text.lower()
    return any(keyword in lower_text for keyword in keywords)

def get_participant_status(html):
    pattern = r'<h2>Entries</h2><table>(.*?)</table>'
    entries_table = re.search(pattern, html, re.DOTALL)
    if not entries_table:
        return []
    entries_table = entries_table.group(1)
    entries_array = entries_table.split('\n')
    entries_array = [entry for entry in entries_array if entry.startswith("<tr class") and entry.endswith("</td></tr>")]
    details = []
    for entry in entries_array:
        last_name = re.search(r'>([^<]+)</a>', entry).group(1)
        first_name = re.search(r'</a></td><td>([^<]+)</td><td>', entry).group(1)
        status = "Confirmed" if "Confirmed" in entry else "Pending" if "Pending" in entry else "Unknown"
        if is_cancelled(html) and status == "Confirmed":
            status = "Cancelled"
        details.append((last_name, first_name, status))
    return details

def get_skippers(html):
    pattern = r'Questions about this event should be directed to the organizer.*?>(.*?)</a>'
    skippers = re.search(pattern, html, re.DOTALL)
    if not skippers:
        return []
    skippers= skippers.group(1).strip().split(', ')

    details=[]
    for skipper in skippers:
        last_name = skipper.split(' ')[-1]
        first_name = " ".join(skipper.split(' ')[:-1])
        if is_cancelled(html):
            details.append((last_name, first_name, "Cancelled"))
        else:
            details.append((last_name, first_name, "Skipper"))
    return details

def get_event_id(url):
    match = re.search(r'[?&]id=([0-9a-fA-F]+)', url)
    return match.group(1) if match else url

def river_sail(title):
    # River sails aren't part of the bluewater keelboat program; exclude them.
    return "river" in (title or "").lower()

# Keywords marking calendar entries that aren't actual sails: boat maintenance /
# work days / haul-outs, IAP and other shore-school classes, and info sessions /
# meetings. Matched as case-insensitive substrings of the event title.
NON_SAILING_KEYWORDS = [
    # maintenance / workdays / haul-outs / rigging
    "work day", "workday", "work party", "workparty", "work session",
    "working party", "winteriz", "dewinter", "haul out", "haulout", "haul-out",
    "repair", "winter prep", "rigging", "downrigging", "gear retrieval",
    # shore school / classes (IAP + standalone class topics)
    "iap", "shore school", "celestial nav", "navigation part", "safety at sea",
    "science of knots", "splices", "living aboard", "chartwork", "chartering",
    "sailing beyond mit", "day skipper", "sailing safely", "weather and enav",
    "intro to bluewater", "intro to keelboat", "introduction to keelboat",
    "intro to offshore", "offshore sailing school",
    # info sessions / meetings / social
    "info session", "info sess", "cruising info", "crew info", "meeting",
    "awards", "mbsa", "history",
]

def non_sailing_event(title):
    tl = (title or "").lower()
    return any(k in tl for k in NON_SAILING_KEYWORDS)


def get_all_participant_data(year, month):
    urls = get_trip_urls(year, month)
    data=[]
    for url in urls:
        try:
            page = urlopen(url)
            html_bytes = page.read()
            html = html_bytes.decode("utf-8", errors='ignore')

            event_id = get_event_id(url)
            title = get_title(html)
            start, end, hours = get_time_data(html)
            racing = is_racing(html)
            participants = get_participant_status(html)
            skippers=get_skippers(html)
            sailors = participants + skippers
        except Exception as err:
            # Some calendar entries (e.g. work days / all-day events) don't
            # parse cleanly; skip them rather than aborting the whole scrape.
            print(f"  WARNING: skipping {url}: {err}")
            continue

        for last_name, first_name, status in sailors:
            data.append({
                "event id": event_id,
                "first name": first_name,
                "last name": last_name,
                "trip name": title,
                "start": start,
                "end": end,
                "duration": hours,
                "race": racing,
                "status": status
            })

    df = pd.DataFrame(data, columns=[
        "event id", "first name", "last name", "trip name", "start", "end", "duration", "race", "status"
    ])
    if not df.empty:
        # Drop river sails and non-sailing entries (work days, classes, meetings),
        # plus any exact duplicate rows within this month.
        df = df[~df["trip name"].apply(river_sail)]
        df = df[~df["trip name"].apply(non_sailing_event)]
        df = df.drop_duplicates(
            subset=["event id", "first name", "last name", "trip name",
                    "start", "end", "duration", "race", "status"],
            keep="first",
        )
        df = df.reset_index(drop=True)
    return df



def main():
  columns = [
    "first name", "last name", "number registrations", "number sails",
    "number races", "number pleasure", "number multi-day",
    "number full day (6+ hr)", "number as skipper", "total sail time (hrs)"
  ]
  df_final = pd.DataFrame(columns=columns)

  # Event-level records are accumulated here and written to sailing_events.csv
  # so downstream tools can aggregate over arbitrary date ranges and build
  # per-person sail histories.
  event_frames = []

  # Start defaults to the beginning of the program but can be overridden with
  # SCRAPE_START_YEAR / SCRAPE_START_MONTH so a scheduled job can scrape just the
  # recent window (e.g. the last year) and merge it into the existing dataset.
  start_year = int(os.environ.get("SCRAPE_START_YEAR", "2007"))
  start_month = int(os.environ.get("SCRAPE_START_MONTH", "1"))
  # End reaches SCRAPE_MONTHS_AHEAD months past the present month (default 2) so
  # upcoming sails that are open for registration are captured too. This also
  # keeps a scheduled run current automatically (through 2027 and beyond).
  now = datetime.now()
  months_ahead = int(os.environ.get("SCRAPE_MONTHS_AHEAD", "2"))
  end_index = now.year * 12 + (now.month - 1) + months_ahead
  end_year = end_index // 12
  end_month = end_index % 12 + 1

  # A future month that doesn't exist on the MIT calendar yet silently defaults
  # to the current month, re-returning events we've already scraped. Track the
  # event ids we've seen and drop repeats so they aren't counted twice.
  seen_event_ids = set()

  for year in range(start_year, end_year+1):
    for month in range(1, 13):
        if year == start_year and month < start_month:
            continue
        if year == end_year and month > end_month:
            break
        print(f"Scraping {year}-{month:02d} ...", flush=True)
        df_all = get_all_participant_data(year, month)
        if not df_all.empty:
            df_all = df_all[~df_all["event id"].isin(seen_event_ids)]
            seen_event_ids.update(df_all["event id"].unique())
            df_all = df_all.reset_index(drop=True)
        event_frames.append(df_all)
        for index, row in df_all.iterrows():
            first_name = row["first name"]
            last_name = row["last name"]

            # Check if the participant exists in df_final
            participant_exists = df_final[(df_final["first name"] == first_name) & (df_final["last name"] == last_name)]

            if participant_exists.empty:
                # Add new participant to df_final
                if row["status"] == "Pending" or row["status"] == "Cancelled":
                    new_row = {
                        "first name": first_name,
                        "last name": last_name,
                        "number registrations": 1,
                        "number sails": 0,
                        "number races": 0,
                    "number pleasure": 0 ,
                    "number multi-day": 0,
                    "number full day (6+ hr)": 0,
                    "number as skipper": 0,
                    "total sail time (hrs)": 0
                }
                else:
                    new_row = {
                        "first name": first_name,
                        "last name": last_name,
                        "number registrations": 1,
                        "number sails": 1,
                        "number races": 1 if row["race"] else 0,
                        "number pleasure": 0 if row["race"] else 1,
                        "number multi-day": 1 if row["duration"] > 24 else 0,
                        "number full day (6+ hr)": 1 if row["duration"] > 6 else 0,
                        "number as skipper": 1 if row["status"] == "Skipper" else 0,
                        "total sail time (hrs)": row["duration"]
                    }
                df_final.loc[len(df_final)] = new_row

            else:
                # Update existing participant's entries
                idx = participant_exists.index[0]
                df_final.at[idx, "number registrations"] += 1
                if row["status"] == "Confirmed" or row["status"] == "Skipper":
                    df_final.at[idx, "number sails"] += 1
                    df_final.at[idx, "number races"] += 1 if row["race"] else 0
                    df_final.at[idx, "number pleasure"] += 0 if row["race"] else 1
                    df_final.at[idx, "number multi-day"] += 1 if row["duration"] > 24 else 0
                    df_final.at[idx, "number full day (6+ hr)"] += 1 if row["duration"] > 6 else 0
                    df_final.at[idx, "number as skipper"] += 1 if row["status"] == "Skipper" else 0
                    df_final.at[idx, "total sail time (hrs)"] += row["duration"]



  # Write the event-level records (one row per participant per event).
  events_df = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
  events_df.to_csv("sailing_events.csv", index=False)
  print(f"Wrote {len(events_df)} event-participant rows to sailing_events.csv")

  df_final_sorted = df_final.sort_values(by="total sail time (hrs)", ascending=False)
  print(df_final_sorted)
  df_final_sorted.to_csv("sailing_data_all_time.csv", index=False)


if __name__ == "__main__":
    main()