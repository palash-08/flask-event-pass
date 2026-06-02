import argparse
import logging
import os
import uuid

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from db import DB_PATH, get_db, init_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("sync_sheet.log")],
)
log = logging.getLogger(__name__)

SPREADSHEET_NAME  = os.getenv("INPUT_SPREADSHEET_NAME", "")
WORKSHEET_NAME    = os.getenv("INPUT_WORKSHEET_NAME",   "Form Responses 1")
SERVICE_ACCT_FILE = os.getenv("SERVICE_ACCOUNT_FILE",   "service_account.json")
EMAIL_COL = 1
NAME_COL  = 2

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def fetch_sheet_rows(spreadsheet_name, worksheet_name, creds_file):
    creds  = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet  = client.open(spreadsheet_name).worksheet(worksheet_name)
    rows   = sheet.get_all_values()

    if not rows:
        log.warning("Sheet is empty.")
        return []

    log.info("Fetched %d rows (including header) from Google Sheets.", len(rows))
    records = []
    seen: set[str] = set()

    for row in rows[1:]:
        email = row[EMAIL_COL].strip().lower() if len(row) > EMAIL_COL else ""
        name  = row[NAME_COL].strip()          if len(row) > NAME_COL  else ""

        if not email or "@" not in email or email in seen:
            continue

        seen.add(email)
        records.append({"email": email, "name": name})

    log.info("Unique valid emails from sheet: %d", len(records))
    return records


def sync_to_db(records, db_path=DB_PATH):
    init_db(db_path)
    inserted = skipped = 0

    with get_db(db_path) as conn:
        for rec in records:
            existing = conn.execute(
                "SELECT id FROM users WHERE email = ?", (rec["email"],)
            ).fetchone()

            if existing:
                skipped += 1
                continue

            token = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users (email, name, token, email_sent, redeemed) VALUES (?, ?, ?, 0, 0)",
                (rec["email"], rec["name"], token),
            )
            inserted += 1
            log.info("Inserted: %s (%s)", rec["email"], rec["name"])

    log.info("Sync complete. Inserted=%d  Skipped=%d", inserted, skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet", default=SPREADSHEET_NAME)
    parser.add_argument("--sheet",       default=WORKSHEET_NAME)
    parser.add_argument("--creds",       default=SERVICE_ACCT_FILE)
    parser.add_argument("--db",          default=DB_PATH)
    args = parser.parse_args()

    rows = fetch_sheet_rows(args.spreadsheet, args.sheet, args.creds)
    if rows:
        sync_to_db(rows, db_path=args.db)
