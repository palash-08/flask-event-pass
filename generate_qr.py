import argparse
import logging
import os
from pathlib import Path

import qrcode
from dotenv import load_dotenv
from PIL import Image

from db import DB_PATH, get_db, init_db

_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_ROOT, ".env"))
load_dotenv(os.path.join(_ROOT, "env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("generate_qr.log")],
)
log = logging.getLogger(__name__)

QR_DIR     = "qrcodes"
LOGO_RATIO = 0.25


def resolve_logo_path() -> str:
    """Path from QR_LOGO_PATH (.env); relative paths are under the project root."""
    raw = os.getenv("QR_LOGO_PATH", "final_qr_logo.png").strip()
    if os.path.isabs(raw):
        return raw
    return os.path.join(_ROOT, raw)


LOGO_PATH = resolve_logo_path()


def make_qr_png(token: str, output_path: str) -> None:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(token)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    qr_w, qr_h = qr_img.size

    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo_max = int(qr_w * LOGO_RATIO)
        logo.thumbnail((logo_max, logo_max), Image.LANCZOS)
        logo_w, logo_h = logo.size
        pad = 6
        padded = Image.new("RGBA", (logo_w + pad * 2, logo_h + pad * 2), (255, 255, 255, 255))
        padded.paste(logo, (pad, pad), logo)
        pos = ((qr_w - padded.width) // 2, (qr_h - padded.height) // 2)
        qr_img.paste(padded, pos, padded)
    else:
        log.warning("Logo not found at %s — generating plain QR", LOGO_PATH)

    qr_img.convert("RGB").save(output_path)


def email_to_filename(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def generate(db_path=DB_PATH, qr_dir=QR_DIR):
    init_db(db_path)
    Path(qr_dir).mkdir(parents=True, exist_ok=True)

    with get_db(db_path) as conn:
        users = conn.execute("SELECT id, email, token FROM users").fetchall()

    total = len(users)
    log.info("Total users in DB: %d", total)

    if total == 0:
        log.warning("No users found. Run sync_sheet.py first.")
        return

    created = skipped = 0
    for user in users:
        png_path = os.path.join(qr_dir, f"{email_to_filename(user['email'])}.png")
        if os.path.exists(png_path):
            skipped += 1
            continue
        make_qr_png(user["token"], png_path)
        log.info("Generated QR for %s", user["email"])
        created += 1

    log.info("Done. Created=%d  Skipped=%d", created, skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",     default=DB_PATH)
    parser.add_argument("--qr-dir", default=QR_DIR)
    args = parser.parse_args()
    generate(db_path=args.db, qr_dir=args.qr_dir)
