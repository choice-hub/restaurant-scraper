"""
Google Sheets export service using gspread + service account credentials.
"""
import os
import json
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive',
]

COLUMNS = [
    'Name',
    'City',
    'Address',
    'Phone',
    'Website',
    'Wolt ID',
    'Cuisine / Kitchen',
    'Rating',
    'Platform URL',
]


def get_client() -> gspread.Client:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise EnvironmentError('GOOGLE_CREDENTIALS_JSON env var is not set.')
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def cleanup_old_sheets(client: gspread.Client, keep: int = 5) -> None:
    """Delete old spreadsheets to keep service account Drive tidy."""
    try:
        sheets = client.list_spreadsheet_files()
        if len(sheets) <= keep:
            return
        # Sort by createdTime ascending, delete oldest
        sheets.sort(key=lambda s: s.get('createdTime', ''))
        for s in sheets[:-keep]:
            client.del_spreadsheet(s['id'])
            print(f"[Sheets] Deleted old sheet: {s['name']}")
    except Exception as e:
        print(f'[Sheets] Cleanup warning: {e}')


def export_to_sheets(restaurants: list[dict], platform: str, location: str, user_email: str = '') -> str:
    """
    Creates a new Google Sheet in the service account's Drive and returns a shareable URL.
    The service account has unlimited Drive storage so no quota issues.
    """
    client = get_client()

    # Clean up old sheets so we don't accumulate them
    cleanup_old_sheets(client, keep=5)

    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    title = f'{platform.capitalize()} Restaurants — {location} — {timestamp}'

    # Create in service account's root Drive (unlimited quota, no dependency on user storage)
    spreadsheet = client.create(title)

    # Make it publicly viewable (anyone with link)
    spreadsheet.share(None, perm_type='anyone', role='reader')

    # Also share with the user as editor so they can find it in "Shared with me"
    if user_email and '@' in user_email:
        try:
            spreadsheet.share(user_email, perm_type='user', role='writer', notify=False)
        except Exception as e:
            print(f'[Sheets] Could not share with user: {e}')

    sheet = spreadsheet.sheet1
    sheet.update_title('Restaurants')

    # Header row
    sheet.append_row(COLUMNS, value_input_option='USER_ENTERED')

    # Format header
    sheet.format('A1:I1', {
        'textFormat': {'bold': True},
        'backgroundColor': {'red': 0.2, 'green': 0.6, 'blue': 0.9},
    })

    # Data rows
    rows = []
    for r in restaurants:
        rows.append([
            r.get('name', ''),
            r.get('city', ''),
            r.get('address', ''),
            r.get('phone', ''),
            r.get('website', ''),
            r.get('legal_id', ''),
            r.get('cuisine', ''),
            r.get('rating', ''),
            r.get('wolt_url', ''),
        ])

    if rows:
        sheet.append_rows(rows, value_input_option='USER_ENTERED')

    # Auto-resize columns
    sheet.columns_auto_resize(0, len(COLUMNS))

    return spreadsheet.url
