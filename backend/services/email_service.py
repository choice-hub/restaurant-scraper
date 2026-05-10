import io
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# Wolt-specific columns
WOLT_COLUMNS = [
    ('Restaurant Name',       'name'),
    ('Brand Name',            'brand_name'),
    ('Phone',                 'phone'),
    ('Website',               'website'),
    ('Address',               'address'),
    ('City',                  'city'),
    ('Country',               'country'),
    ('Cuisine / Kitchen',     'cuisine'),
    ('Rating',                'rating'),
    ('Merchant / Legal Co.',  'merchant_name'),
    ('Business ID',           'business_id'),
    ('Legal Street',          'legal_street'),
    ('Legal City',            'legal_city'),
    ('Legal Post Code',       'legal_post_code'),
    ('Legal Country',         'legal_country'),
    ('Platform URL',          'platform_url'),
]

# Bolt-specific columns
BOLT_COLUMNS = [
    ('Restaurant Name',       'name'),
    ('Cuisine / Kitchen',     'cuisine'),
    ('Rating',                'rating'),
    ('Review Count',          'review_count'),
    ('Delivery Fee',          'delivery_fee'),
    ('Delivery Time',         'delivery_time'),
    ('Address',               'address'),
    ('City',                  'city'),
    ('Platform URL',          'platform_url'),
]

# Foodora-specific columns (sitemap only: name + city + country + URL)
FOODORA_COLUMNS = [
    ('Restaurant Name',   'name'),
    ('City',              'city'),
    ('Country',           'country'),
    ('Platform URL',      'platform_url'),
]

PLATFORM_COLUMNS = {
    'wolt':    WOLT_COLUMNS,
    'bolt':    BOLT_COLUMNS,
    'foodora': FOODORA_COLUMNS,
}

HEADER_COLORS = {
    'wolt':    '009DE0',   # Wolt blue
    'bolt':    '34C759',   # Bolt green
    'foodora': 'E2213D',   # Foodora red
}


def _add_sheet(wb, platform: str, location: str, restaurants: list):
    """Add one sheet to workbook for a given platform."""
    columns = PLATFORM_COLUMNS.get(platform, WOLT_COLUMNS)
    color   = HEADER_COLORS.get(platform, '1A73E8')

    sheet_title = f'{platform.capitalize()} - {location}'[:31]
    ws = wb.create_sheet(title=sheet_title)

    hfont  = Font(bold=True, color='FFFFFF')
    hfill  = PatternFill('solid', fgColor=color)
    halign = Alignment(horizontal='center', vertical='center', wrap_text=False)

    for ci, (header, _) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=ci, value=header)
        cell.font, cell.fill, cell.alignment = hfont, hfill, halign

    for ri, r in enumerate(restaurants, start=2):
        for ci, (_, key) in enumerate(columns, start=1):
            ws.cell(row=ri, column=ci, value=r.get(key, ''))

    for ci in range(1, len(columns) + 1):
        col_letter = get_column_letter(ci)
        max_len = max(
            len(str(ws.cell(row=r, column=ci).value or ''))
            for r in range(1, min(len(restaurants) + 2, 200))
        )
        ws.column_dimensions[col_letter].width = min(max_len + 4, 50)


def build_excel(results_by_platform: dict, location: str) -> bytes:
    """Build an Excel file with one sheet per platform."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    for platform, restaurants in results_by_platform.items():
        if restaurants:
            _add_sheet(wb, platform, location, restaurants)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _send(to_email: str, subject: str, html: str, attachment: bytes = None, filename: str = None):
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASSWORD')

    if not smtp_user or not smtp_pass:
        print('[Email] SMTP credentials not set — skipping.')
        return

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From']    = smtp_user
    msg['To']      = to_email
    msg.attach(MIMEText(html, 'html'))

    if attachment and filename:
        part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
        msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())

    print(f'[Email] Sent to {to_email}: {subject}')


def send_completion_email(to_email: str, results_by_platform: dict, location: str):
    """
    results_by_platform: {"wolt": [...], "bolt": [...]}
    Builds a single Excel with one tab per platform and emails it.
    """
    excel_bytes = build_excel(results_by_platform, location)

    platforms_str = ' + '.join(p.capitalize() for p in results_by_platform if results_by_platform[p])
    total = sum(len(v) for v in results_by_platform.values())
    safe_loc = location.replace(', ', '_').replace(' ', '_')
    filename = f'{safe_loc}_{platforms_str.replace(" + ", "_")}.xlsx'

    subject = f'✅ Scraping done — {total} restaurants from {location} ({platforms_str})'

    # Build table rows per platform
    platform_rows = ''
    for plat, restaurants in results_by_platform.items():
        if restaurants:
            platform_rows += f"""
        <tr>
          <td style="padding:6px 12px;background:#f4f6fb;font-weight:bold;">{plat.capitalize()}</td>
          <td style="padding:6px 12px;"><strong>{len(restaurants)}</strong> restaurants</td>
        </tr>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
      <h2 style="color:#009de0;">🍽️ Your restaurant data is ready!</h2>
      <p>The scraping job completed successfully. The Excel file is attached.</p>
      <table style="border-collapse:collapse;margin:16px 0;">
        <tr><td style="padding:6px 12px;background:#f4f6fb;font-weight:bold;">Location</td>
            <td style="padding:6px 12px;">{location}</td></tr>
        {platform_rows}
        <tr><td style="padding:6px 12px;background:#f4f6fb;font-weight:bold;">Total</td>
            <td style="padding:6px 12px;"><strong>{total}</strong> restaurants</td></tr>
        <tr><td style="padding:6px 12px;background:#f4f6fb;font-weight:bold;">File</td>
            <td style="padding:6px 12px;">{filename}</td></tr>
      </table>
      <p style="margin-top:24px;color:#6b7280;font-size:0.85rem;">Generated by Restaurant Scraper.</p>
    </body></html>
    """
    _send(to_email, subject, html, attachment=excel_bytes, filename=filename)


def send_error_email(to_email: str, platform: str, location: str, error_message: str):
    subject = f'❌ Scraping failed — {platform.capitalize()} / {location}'
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
      <h2 style="color:#ef4444;">❌ Scraping stopped due to an error</h2>
      <table style="border-collapse:collapse;margin:16px 0;">
        <tr><td style="padding:6px 12px;background:#fff5f5;font-weight:bold;">Platform</td>
            <td style="padding:6px 12px;">{platform.capitalize()}</td></tr>
        <tr><td style="padding:6px 12px;background:#fff5f5;font-weight:bold;">Location</td>
            <td style="padding:6px 12px;">{location}</td></tr>
        <tr><td style="padding:6px 12px;background:#fff5f5;font-weight:bold;">Error</td>
            <td style="padding:6px 12px;color:#ef4444;"><code>{error_message}</code></td></tr>
      </table>
      <p style="color:#6b7280;font-size:0.85rem;">Generated by Restaurant Scraper.</p>
    </body></html>
    """
    _send(to_email, subject, html)
