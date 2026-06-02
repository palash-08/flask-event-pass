import csv
import io
import logging
import os
from datetime import datetime, timezone, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, render_template_string, request

from db import DB_PATH, get_db, init_db
from sheet_logger import log_redemption_to_sheet

load_dotenv()

DB_PATH = "util_scripts/events.db"

app = Flask(__name__)

EVENT_NAME = os.getenv("EVENT_NAME", "Fest420")

AUTHORISED_SCANNERS: set[str] = {
    e.strip() for e in os.getenv("SCANNER_EMAILS", "").split(",") if e.strip()
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("app.log")],
)
log = logging.getLogger(__name__)

with app.app_context():
    init_db(DB_PATH)

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def require_scanner(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        data          = request.get_json(silent=True) or {}
        scanner_email = (
            data.get("scanner_email") or request.args.get("scanner_email", "")
        ).strip().lower()
        if scanner_email not in {e.lower() for e in AUTHORISED_SCANNERS}:
            log.warning("Unauthorised attempt by: %s", scanner_email or "<none>")
            return jsonify({"status": "error", "message": "Unauthorised scanner"}), 403
        return f(*args, **kwargs)
    return wrapper


_CSS = """
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Exo+2:wght@400;700;900&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Exo 2',Arial,sans-serif;background:#080c14;color:#cdd9e5;
       min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:#0d1526;border:1px solid #1e3a5f;border-radius:16px;
        padding:36px 28px;max-width:400px;width:100%;text-align:center}
  .icon{font-size:3rem;margin-bottom:10px}
  h2{font-size:1.3rem;font-weight:900;letter-spacing:.05em;margin-bottom:12px}
  p{color:#7a9ab5;line-height:1.6;font-size:.95rem;margin-top:6px}
  .tag{display:inline-block;background:#0a1f38;border:1px solid #1e3a5f;border-radius:6px;
       padding:4px 14px;font-family:monospace;font-size:.82rem;color:#00e5ff;margin-top:10px}
  .sub{font-family:monospace;font-size:.72rem;color:#2a4a60;margin-top:14px;word-break:break-all}
</style>
"""

TMPL_INVALID = _CSS + """
<div class="card">
  <div class="icon">❌</div>
  <h2 style="color:#ff3d5a">Invalid Link</h2>
  <p>{{ message }}</p>
</div>
"""


@app.route("/scan", methods=["POST"])
@require_scanner
def scan():
    data          = request.get_json(silent=True) or {}
    token         = (data.get("token") or "").strip()
    scanner_email = (data.get("scanner_email") or "").strip()

    if not token:
        return jsonify({"status": "error", "message": "No token provided"}), 400

    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, email, name, redeemed, redeemed_at FROM users WHERE token = ?",
            (token,),
        ).fetchone()

        if not row:
            log.info("SCAN invalid token=%.8s scanner=%s", token, scanner_email)
            return jsonify({"status": "invalid", "message": "Invalid token — QR not recognised"}), 404

        if row["redeemed"]:
            log.info("SCAN used email=%s scanner=%s", row["email"], scanner_email)
            return jsonify({
                "status":      "already_used",
                "message":     "Refreshment already collected.",
                "email":       row["email"],
                "redeemed_at": row["redeemed_at"],
            }), 409

        ts   = now_ist()
        name = row["name"] or ""
        conn.execute(
            "UPDATE users SET redeemed = 1, redeemed_at = ? WHERE id = ?",
            (ts, row["id"]),
        )

    log.info("SCAN success email=%s scanner=%s", row["email"], scanner_email)

    log_redemption_to_sheet(
        email         = row["email"],
        name          = name,
        redeemed_at   = ts,
        scanner_email = scanner_email,
        token         = token,
    )

    return jsonify({
        "status":  "success",
        "message": "Refreshment granted!",
        "email":   row["email"],
        "name":    name,
    }), 200


@app.route("/stats")
def stats():
    with get_db(DB_PATH) as conn:
        total    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        qr_sent  = conn.execute("SELECT COUNT(*) FROM users WHERE email_sent=1").fetchone()[0]
        redeemed = conn.execute("SELECT COUNT(*) FROM users WHERE redeemed=1").fetchone()[0]
    return jsonify({
        "total":         total,
        "qr_email_sent": qr_sent,
        "redeemed":      redeemed,
        "remaining":     total - redeemed,
    })


@app.route("/export")
@require_scanner
def export_csv():
    with get_db(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT email, name, redeemed_at FROM users WHERE redeemed=1 ORDER BY redeemed_at"
        ).fetchall()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["email", "name", "redeemed_at"])
    for r in rows:
        w.writerow([r["email"], r["name"], r["redeemed_at"]])

    resp = make_response(out.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=redeemed_users.csv"
    resp.headers["Content-Type"] = "text/csv"
    log.info("CSV export: %d rows", len(rows))
    return resp


@app.route("/")
def health():
    return ("<h3 style='font-family:monospace;padding:20px;color:#00e5ff;background:#080c14'>"
            "QR Redemption API<br/><br/>"
            "<a href='/stats' style='color:#7a9ab5'>stats</a></h3>")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
