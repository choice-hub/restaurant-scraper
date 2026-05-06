"""
Google Sheets export service using gspread + service account credentials.

Setup:
  1. Create a Google Cloud project
  2. Enable Google Sheets API and Google Drive API
  3. Create a Service Account and download credentials.json
  4. Set GOOGLE_CREDENTIALS_JSON env var to the contents of credentials.json
  5. Set GOOGLE_DRIVE_FOLDER_ID (optional) to auto-organize sheets
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
    'Legal ID',
    'Cuisine / Kitchen',
    'Platform URL',
]


def get_client() -> gspread.Client:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise EnvironmentError(
            'GOOGLE_CREDENTIALS_JSON env var is not set. '
            'See backend/.env.example for setup instructions.'
        )
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def export_to_sheets(restaurants: list[dict], platform: str, location: str) -> str:
    """
    Creates a new Google Sheet with restaurant data and returns the shareable URL.
    """
    client = get_client()

    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    title = f'{platform.capitalize()} Restaurants — {location} — {timestamp}'

    folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
    if folder_id:
        spreadsheet = client.create(title, folder_id=folder_id)
    else:
        spreadsheet = client.create(title)

    # Make it publicly viewable (anyone with link)
    spreadsheet.share(None, perm_type='anyone', role='reader')

    sheet = spreadsheet.sheet1
    sheet.update_title('Restaurants')

    # Header row
    sheet.append_row(COLUMNS, value_input_option='USER_ENTERED')

    # Format header
    sheet.format('A1:H1', {
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
            r.get('wolt_url', ''),
        ])

    if rows:
        sheet.append_rows(rows, value_input_option='USER_ENTERED')

    # Auto-resize columns
    sheet.columns_auto_resize(0, len(COLUMNS) - 1)

    return spreadsheet.url
