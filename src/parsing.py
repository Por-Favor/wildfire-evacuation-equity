"""Parsing helpers for the WatchDuty changelog data."""
import json
import pandas as pd


def safe_json_loads(s):
    """Parse a JSON string, returning None if it fails or is missing."""
    if pd.isna(s):
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


# Fields we care about in the changelog. Each represents a critical
# moment in a fire's lifecycle that we want a timestamp for.
PRIORITY_FIELDS = [
    'radio_traffic_indicates_rate_of_spread',
    'radio_traffic_indicates_structure_threat',
    'radio_traffic_indicates_spotting',
    'data.evacuation_orders',
    'data.evacuation_warnings',
    'data.evacuation_advisories',
    'notification_type',
    'data.acreage',
]


def parse_changelog(changelog_df):
    """
    Walk the changelog once. For each fire, find the first timestamp
    each priority event occurred and the last reported acreage.

    Returns a DataFrame with one row per fire.
    """
    timelines = {}

    for _, row in changelog_df.iterrows():
        gid = row['geo_event_id']
        date = row['date_created']
        changes = safe_json_loads(row['changes'])

        if changes is None:
            continue

        if gid not in timelines:
            timelines[gid] = {
                'first_seen': date,
                'last_seen': date,
                'first_events': {},
                'last_acreage': None,
                'ros_value': None,
            }

        # Update the seen-window
        if date < timelines[gid]['first_seen']:
            timelines[gid]['first_seen'] = date
        if date > timelines[gid]['last_seen']:
            timelines[gid]['last_seen'] = date

        # Record the first occurrence of each priority field
        for field in PRIORITY_FIELDS:
            if field in changes and field not in timelines[gid]['first_events']:
                timelines[gid]['first_events'][field] = date

        # Capture the rate-of-spread severity value (not just timestamp)
        ros_field = 'radio_traffic_indicates_rate_of_spread'
        if ros_field in changes:
            new_value = changes[ros_field][1] if len(changes[ros_field]) > 1 else None
            if new_value:
                timelines[gid]['ros_value'] = new_value

        # Capture the most recent acreage value
        if 'data.acreage' in changes:
            new_value = changes['data.acreage'][1] if len(changes['data.acreage']) > 1 else None
            if new_value is not None:
                timelines[gid]['last_acreage'] = new_value

    # Convert to DataFrame
    rows = []
    for gid, tl in timelines.items():
        row = {
            'geo_event_id': gid,
            'first_seen': tl['first_seen'],
            'last_seen': tl['last_seen'],
            'ros_value': tl['ros_value'],
            'last_acreage': tl['last_acreage'],
        }
        for field in PRIORITY_FIELDS:
            row[f'first_{field}'] = tl['first_events'].get(field)
        rows.append(row)

    return pd.DataFrame(rows)