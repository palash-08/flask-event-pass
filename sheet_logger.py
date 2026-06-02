import logging
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SERVICE_ACCT_FILE     = os.getenv("SERVICE_ACCOUNT_FILE",  "service_account.json")
OUTPUT_SPREADSHEET_ID = os.getenv("OUTPUT_SPREADSHEET_ID", "")
OUTPUT_WORKSHEET_NAME = os.getenv("OUTPUT_WORKSHEET_NAME", "Sheet1")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER = ["email", "name", "redeemed_at", "scanner_email", "token"]

log = logging.getLogger(__name__)

_client    = None
_worksheet = None


def _get_worksheet():
    global _client, _worksheet

    if _worksheet is not None:
        return _worksheet

    creds       = Credentials.from_service_account_file(SERVICE_ACCT_FILE, scopes=SCOPES)
    _client     = gspread.authorize(creds)
    spreadsheet = _client.open_by_key(OUTPUT_SPREADSHEET_ID)

    try:
        ws = spreadsheet.worksheet(OUTPUT_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=OUTPUT_WORKSHEET_NAME, rows=1000, cols=len(HEADER))
        log.info("Created worksheet: %s", OUTPUT_WORKSHEET_NAME)

    if not ws.row_values(1):
        ws.append_row(HEADER, value_input_option="RAW")
        log.info("Header row written.")

    _worksheet = ws
    return _worksheet


def log_redemption_to_sheet(email, name, redeemed_at, scanner_email, token=""):
    try:
        ws  = _get_worksheet()
        row = [email, name or "", redeemed_at, scanner_email or "", token or ""]
        ws.append_row(row, value_input_option="USER_ENTERED")
        log.info("Sheet log appended: %s @ %s", email, redeemed_at)

    except gspread.exceptions.APIError as exc:
        log.warning("Sheet API error (scan still succeeded): %s", exc)
        global _worksheet
        _worksheet = None

    except Exception as exc:
        log.warning("Sheet logger error: %s", exc)
        _worksheet = None
