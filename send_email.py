import argparse
import logging
import os
import smtplib
import time
from email.mime.image     import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from pathlib import Path

from dotenv import load_dotenv

from db import DB_PATH, get_db, init_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("send_email.log")],
)
log = logging.getLogger(__name__)

GMAIL_ADDRESS  = os.getenv("GMAIL_ADDRESS",  "")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS", "")
EVENT_NAME     = os.getenv("EVENT_NAME",     "Tech Fest 2025")
QR_DIR         = "qrcodes"
DELAY_SECONDS  = 2
MAX_RETRIES    = 3


def email_to_filename(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def build_qr_email(to_address, name, token, qr_path, sender):
    display_name = name or to_address.split("@")[0].title()

    msg = MIMEMultipart("related")
    msg["Subject"] = f"Your Event Pass – {EVENT_NAME}"
    msg["From"]    = sender
    msg["To"]      = to_address

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:580px;margin:auto;color:#222">
      <div style="background:#080c14;padding:24px 32px;border-radius:10px 10px 0 0">
        <h2 style="color:#00e5ff;margin:0;font-size:1.4rem;letter-spacing:.04em">
          Your Pass is Ready – {EVENT_NAME}
        </h2>
      </div>
      <div style="border:1px solid #dde;border-top:none;border-radius:0 0 10px 10px;padding:32px">
        <p>Hi <strong>{display_name}</strong>,</p>
        <p>Show the QR code below at the counter to collect your goodies.</p>
        <p style="text-align:center;margin:32px 0">
          <img src="cid:qrcode" alt="Your QR Pass" width="240" height="240"
               style="border:4px solid #00e5ff;border-radius:10px"/>
        </p>
        <p style="font-size:.82em;color:#666;text-align:center">
          Token: <code style="word-break:break-all">{token}</code><br/>
          <em>Valid for one use only. Do not share.</em>
        </p>
        <hr style="border:none;border-top:1px solid #eee;margin:28px 0"/>
        <p style="font-size:.8em;color:#999">
          If you have any issues, show this email at the counter and staff will assist you.
        </p>
      </div>
    </body></html>
    """

    msg.attach(MIMEText(html_body, "html"))

    with open(qr_path, "rb") as fh:
        img_part = MIMEImage(fh.read(), _subtype="png")
    img_part.add_header("Content-ID", "<qrcode>")
    img_part.add_header("Content-Disposition", "inline", filename=Path(qr_path).name)
    msg.attach(img_part)

    return msg


def send_with_retry(smtp, msg, to_address, sender):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            smtp.sendmail(sender, to_address, msg.as_string())
            return True
        except smtplib.SMTPException as exc:
            log.warning("Attempt %d failed for %s: %s", attempt, to_address, exc)
            time.sleep(attempt * 3)
    return False


def send_qr_emails(db_path=DB_PATH, qr_dir=QR_DIR, limit=None):
    init_db(db_path)

    with get_db(db_path) as conn:
        sql = "SELECT id, email, name, token FROM users WHERE email_sent = 0"
        if limit:
            sql += f" LIMIT {limit}"
        users = conn.execute(sql).fetchall()

    log.info("Users pending QR email: %d", len(users))
    if not users:
        log.info("Nothing to send.")
        return

    sent_ok = sent_fail = 0

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        log.info("SMTP login successful.")

        for user in users:
            qr_path = os.path.join(qr_dir, f"{email_to_filename(user['email'])}.png")

            if not os.path.exists(qr_path):
                log.error("QR PNG missing for %s — run generate_qr.py first", user["email"])
                continue

            msg = build_qr_email(
                to_address=user["email"],
                name=user["name"] or "",
                token=user["token"],
                qr_path=qr_path,
                sender=GMAIL_ADDRESS,
            )

            ok = send_with_retry(smtp, msg, user["email"], GMAIL_ADDRESS)

            with get_db(db_path) as conn:
                if ok:
                    conn.execute("UPDATE users SET email_sent = 1 WHERE id = ?", (user["id"],))
                    log.info("Sent to %s", user["email"])
                    sent_ok += 1
                else:
                    log.error("Failed: %s", user["email"])
                    sent_fail += 1

            time.sleep(DELAY_SECONDS)

    log.info("Done. Sent=%d  Failed=%d", sent_ok, sent_fail)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",     default=DB_PATH)
    parser.add_argument("--qr-dir", default=QR_DIR)
    parser.add_argument("--limit",  type=int)
    args = parser.parse_args()
    send_qr_emails(db_path=args.db, qr_dir=args.qr_dir, limit=args.limit)
