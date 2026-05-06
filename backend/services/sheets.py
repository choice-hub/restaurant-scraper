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
from googleapiclient.discovery import build
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


def get_credentials() -> Credentials:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise EnvironmentError('GOOGLE_CREDENTIALS_JSON env var is not set.')
    creds_dict = json.loads(creds_json)
    return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)


def cleanup_service_account_files(drive_service, folder_id: str) -> None:
    """Delete old sheets in the folder to keep service account quota clear."""
    try:
        res = drive_service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet'",
            fields='files(id, name, createdTime)',
            orderBy='createdTime',
        ).execute()
        files = res.get('files', [])
        # Keep the 3 most recent, delete the rest
        for f in files[:-3]:
            drive_service.files().delete(fileId=f['id']).execute()
            print(f"[Sheets] Deleted old sheet: {f['name']}")
    except Exception as e:
        print(f'[Sheets] Cleanup warning: {e}')


def export_to_sheets(restaurants: list[dict], platform: str, location: str, user_email: str = '') -> str:
    """
    Creates a new Google Sheet with restaurant data and returns the shareable URL.
    Transfers ownership to user_email so storage counts against user, not service account.
    """
    creds = get_credentials()
    client = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)

    folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')

    # Clean up old sheets to avoid service account quota issues
    if folder_id:
        cleanup_service_account_files(drive_service, folder_id)

    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    title = f'{platform.capitalize()} Restaurants — {location} — {timestamp}'

    if folder_id:
        spreadsheet = client.create(title, folder_id=folder_id)
    else:
        spreadsheet = client.create(title)

    # Transfer ownership to the requesting user so storage is on their account
    if user_email and '@' in user_email:
        try:
            spreadsheet.share(user_email, perm_type='user', role='owner', notify=False)
            print(f'[Sheets] Transferred ownership to {user_email}')
        except Exception as e:
            print(f'[Sheets] Could not transfer ownership: {e}')

    # Make it publicly viewable (anyone with link)
    spreadsheet.share(None, perm_type='anyone', role='reader')

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
