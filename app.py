"""
Amarseba SMS Telegram Bot — Railway (Hardcoded + SQLite on Volume)
Admin fixed by chat_id — only admin can change API key.
"""
import os
import uuid
import sqlite3
import traceback
import requests
import cloudscraper
from flask import Flask, request, jsonify

# ==================== CONFIG (HARDCODED) ====================
TELEGRAM_BOT_TOKEN = "8896805760:AAG6f5vU_MLuNK3mBTI2Gc74MV6Uds2_1n8"
AMARSEBA_API_KEY_DEFAULT = "sk-ams-live-Xqoc4Aley0GyV8XbzXjZCdReeePqOrpYSjNP0Cc5k8pnFLLh"
AMARSEBA_BASE_URL = "https://e-amarseba.com/api/v1"

# ⚠️ এখানে আপনার Telegram chat_id বসান (শুধু সংখ্যা, কোনো @ নয়)
ADMIN_CHAT_ID = "1700797877,6552783238"

# Railway persistent volume mount path
DB_PATH = "/data/amarseba.db"
# ===========================================================

app = Flask(__name__)

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)


# ---------------- SQLite Storage ----------------
def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def db_get(key):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"db_get error: {e}")
        return None


def db_set(key, value):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"db_set error: {e}")
        return False


def db_del(key):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM config WHERE key = ?", (key,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"db_del error: {e}")
        return False


# ---------------- Config Helpers ----------------
def get_api_key():
    return db_get("api_key") or AMARSEBA_API_KEY_DEFAULT


def is_admin(chat_id):
    """শুধু hardcoded ADMIN_CHAT_ID-ই admin।"""
    return str(chat_id) == str(ADMIN_CHAT_ID)


def get_headers():
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def mask_key(k):
    if not k or len(k) < 16:
        return "***"
    return f"{k[:12]}...{k[-4:]}"


# ---------------- Telegram Helpers ----------------
def tg_send(chat_id, text, parse_mode="HTML"):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=20,
        )
        print(f"tg_send status={r.status_code}")
        return r
    except Exception as e:
        print(f"tg_send error: {e}")
        return None


def tg_typing(chat_id):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=10,
        )
    except Exception as e:
        print(f"tg_typing error: {e}")


# ---------------- Amarseba Helpers ----------------
def amarseba_send(phone, body):
    h = get_headers()
    h["Idempotency-Key"] = str(uuid.uuid4())
    try:
        r = scraper.post(
            f"{AMARSEBA_BASE_URL}/bulk-sms/send",
            headers=h, json={"to": phone, "body": body}, timeout=50,
        )
        print(f"amarseba_send status={r.status_code}")
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"success": False, "message": r.text[:300]}
    except Exception as e:
        return 0, {"success": False, "message": str(e)}


def amarseba_balance():
    try:
        r = scraper.get(
            f"{AMARSEBA_BASE_URL}/wallet/balance",
            headers=get_headers(), timeout=20,
        )
        print(f"amarseba_balance status={r.status_code}")
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"success": False, "message": r.text[:300]}
    except Exception as e:
        return 0, {"success": False, "message": str(e)}


def is_valid_phone(p):
    c = p.replace("+", "").replace("-", "").replace(" ", "")
    return c.isdigit() and 10 <= len(c) <= 14


# ---------------- Update Handler ----------------
def handle_update(update):
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        print(f"Incoming: chat_id={chat_id} text={text!r}")

        if not text:
            return

        # ---------- /start, /help ----------
        if text in ("/start", "/help"):
            base = (
                "🤖 <b>SAKIB CUSTOM SMS BOT</b>\n\n"
                "SMS পাঠাতে:\n"
                "<code>01712345678 আপনার মেসেজ</code>\n\n"
                "<b>কমান্ড:</b>\n"
                "• /balance — ব্যালেন্স\n"
                "• /id — chat ID\n"
                "• /debug — সিস্টেম টেস্ট\n"
            )
            if is_admin(chat_id):
                base += (
                    "\n<b>👑 Admin কমান্ড:</b>\n"
                    "• /setkey &lt;api_key&gt; — API key সেট\n"
                    "• /delkey — key মুছুন (default-এ ফিরবে)\n"
                )
            tg_send(chat_id, base)
            return

        # ---------- /id ----------
        if text == "/id":
            tg_send(chat_id, f"🆔 chat ID: <code>{chat_id}</code>")
            return

        # ---------- /setkey (ADMIN ONLY) ----------
        if text.startswith("/setkey"):
            if not is_admin(chat_id):
                tg_send(chat_id, "⛔ শুধুমাত্র admin API key সেট করতে পারবে।")
                return

            parts = text.split(None, 1)
            if len(parts) < 2:
                tg_send(chat_id, "ব্যবহার: <code>/setkey sk-ams-live-...</code>")
                return

            new_key = parts[1].strip()
            if not new_key.startswith("sk-ams-"):
                tg_send(chat_id, "❌ API key অবশ্যই <code>sk-ams-</code> দিয়ে শুরু হবে।")
                return

            if db_set("api_key", new_key):
                tg_send(chat_id,
                    "✅ <b>API key সেভ হয়েছে</b>\n\n"
                    f"<code>{mask_key(new_key)}</code>\n\n"
                    "এখন /balance দিয়ে টেস্ট করুন।"
                )
            else:
                tg_send(chat_id, "❌ সেভ করা যায়নি। Volume mount চেক করুন।")
            return

        # ---------- /delkey (ADMIN ONLY) ----------
        if text == "/delkey":
            if not is_admin(chat_id):
                tg_send(chat_id, "⛔ শুধুমাত্র admin।")
                return
            db_del("api_key")
            tg_send(chat_id, "🗑️ API key মুছে ফেলা হয়েছে। এখন default ব্যবহার হবে।")
            return

        # ---------- /debug ----------
        if text == "/debug":
            tg_typing(chat_id)
            try:
                status, data = amarseba_balance()
                if status == 200 and data.get("success"):
                    d = data["data"]
                    tg_send(chat_id,
                        "✅ <b>BOT OK</b>\n\n"
                        f"💰 ব্যালেন্স: {d.get('balance')} {d.get('currency')}\n"
                        f"📌 স্ট্যাটাস: {d.get('status')}\n"
                        f"🔑 Key: <code>{mask_key(get_api_key())}</code>"
                    )
                else:
                    tg_send(chat_id,
                        f"❌ <b>Amarseba fail</b>\nHTTP: {status}\n"
                        f"<code>{str(data)[:300]}</code>"
                    )
            except Exception as e:
                tg_send(chat_id, f"⚠️ Exception: <code>{e}</code>")
            return

        # ---------- /balance ----------
        if text == "/balance":
            tg_typing(chat_id)
            try:
                status, data = amarseba_balance()
            except Exception as e:
                tg_send(chat_id, f"⚠️ Network error: <code>{e}</code>")
                return
            if status == 200 and data.get("success"):
                d = data["data"]
                tg_send(chat_id,
                    f"💰 <b>ব্যালেন্স:</b> {d.get('balance')} {d.get('currency')}\n"
                    f"📌 স্ট্যাটাস: {d.get('status')}"
                )
            else:
                tg_send(chat_id,
                    f"❌ <b>HTTP {status}</b>\n<code>{str(data)[:300]}</code>"
                )
            return

        # ---------- Send SMS ----------
        payload_text = text
        if text.startswith("/send"):
            payload_text = text[5:].strip()

        parts = payload_text.split(None, 1)
        if len(parts) < 2:
            tg_send(chat_id,
                "❌ ফরম্যাট ভুল।\n\nএভাবে পাঠান:\n"
                "<code>01712345678 আপনার মেসেজ</code>"
            )
            return

        phone, body = parts[0], parts[1].strip()
        if not is_valid_phone(phone):
            tg_send(chat_id, "❌ সঠিক নম্বর দিন (যেমন: 01712345678)")
            return
        if not body:
            tg_send(chat_id, "❌ মেসেজ খালি")
            return

        tg_typing(chat_id)
        try:
            status, data = amarseba_send(phone, body)
        except Exception as e:
            tg_send(chat_id, f"⚠️ Network error:\n<code>{e}</code>")
            return

        if status in (200, 201, 202) and data.get("success"):
            d = data.get("data", {})
            tg_send(chat_id,
                "✅ <b>SMS পাঠানো হয়েছে!</b>\n\n"
                f"📊 স্ট্যাটাস: <b>{d.get('status', '-')}</b>\n"
                f"👥 প্রাপক: {d.get('recipient_count', '-')}\n"
                f"🧩 পার্ট: {d.get('total_parts', '-')}\n"
                f"💵 খরচ: {d.get('total_cost', '-')}\n"
                f"💰 ব্যালেন্স: {d.get('balance_after', '-')}\n"
                f"🆔 <code>{d.get('batch_id', '-')}</code>"
            )
        else:
            tg_send(chat_id,
                f"❌ <b>HTTP {status}</b>\n<code>{str(data)[:300]}</code>"
            )

    except Exception as e:
        print(f"handle_update CRASH: {e}")
        print(traceback.format_exc())
        try:
            tg_send(message["chat"]["id"],
                    f"⚠️ Internal error:\n<code>{str(e)[:200]}</code>")
        except Exception:
            pass


# ==================== Flask Routes ====================
@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "POST":
        update = request.get_json(silent=True) or {}
        try:
            handle_update(update)
        except Exception as e:
            print(f"root POST error: {e}")
        return jsonify({"ok": True})
    return jsonify({
        "status": "ok",
        "bot": "SAKIB CUSTOM SMS BOT",
        "storage": "sqlite_volume",
        "admin_configured": ADMIN_CHAT_ID != "PASTE_YOUR_CHAT_ID_HERE",
    })


@app.route("/webhook", methods=["GET", "POST"])
@app.route("/api/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "POST":
        update = request.get_json(silent=True) or {}
        try:
            handle_update(update)
        except Exception as e:
            print(f"webhook POST error: {e}")
        return jsonify({"ok": True})
    return jsonify({"status": "ok", "endpoint": "webhook"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/set-webhook", methods=["GET"])
def set_webhook():
    host = request.host_url.rstrip("/")
    webhook_url = f"{host}/webhook"
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            params={"url": webhook_url, "drop_pending_updates": "true"},
            timeout=20,
        )
        return jsonify({"webhook_url": webhook_url, "result": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/webhook-info", methods=["GET"])
def webhook_info():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo",
            timeout=20,
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/delete-webhook", methods=["GET"])
def delete_webhook():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
            timeout=20,
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== Init ====================
ensure_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
