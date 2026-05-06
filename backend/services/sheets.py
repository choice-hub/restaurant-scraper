"""
Google Sheets export service using gspread + service account credentials.

The service account cannot create new Google Sheet files (no Drive storage quota).
Instead, we write to a pre-existing spreadsheet shared with the service account.
Each scrape run adds a new worksheet tab. Set GOOGLE_SPREADSHEET_ID env var.
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


def export_to_sheets(restaurants: list[dict], platform: str, location: str, user_email: str = '') -> str:
    """
    Adds a new worksheet tab to a pre-existing shared spreadsheet.
    Set GOOGLE_SPREADSHEET_ID env var to the spreadsheet ID.
    Returns the URL of the new worksheet tab.
    """
    spreadsheet_id = os.environ.get('GOOGLE_SPREADSHEET_ID')
    if not spreadsheet_id:
        raise EnvironmentError(
            'GOOGLE_SPREADSHEET_ID env var is not set. '
            'Create a Google Sheet, share it with the service account as Editor, '
            'then set GOOGLE_SPREADSHEET_ID to the sheet ID from its URL.'
        )

    client = get_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    # Create a new worksheet tab for this run
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    tab_title = f'{platform.capitalize()} {location} {timestamp}'[:100]

    # Remove the tab if it somehow exists already
    try:
        existing = spreadsheet.worksheet(tab_title)
        spreadsheet.del_worksheet(existing)
    except gspread.exceptions.WorksheetNotFound:
        pass

    # Clean up old tabs — keep at most 20
    worksheets = spreadsheet.worksheets()
    if len(worksheets) >= 20:
        # Delete the oldest tab (first one, assuming tabs are ordered by creation)
        try:
            spreadsheet.del_worksheet(worksheets[0])
        except Exception:
            pass

    sheet = spreadsheet.add_worksheet(title=tab_title, rows=len(restaurants) + 2, cols=len(COLUMNS))

    # Header row
    sheet.append_row(COLUMNS, value_input_option='USER_ENTERED')

    # Format header
    sheet.format(f'A1:{chr(64 + len(COLUMNS))}1', {
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

    # Return URL pointing directly to this tab
    return f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet.id}'
