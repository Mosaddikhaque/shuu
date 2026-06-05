import pandas as pd
import telebot
import requests
import time
import os
import logging
import random
import html as html_lib

# ─────────────────────────────────────────────
#  🔧  CONFIGURATION
# ─────────────────────────────────────────────
BOT_TOKEN  = os.environ["8951063494:AAHTFRdm3n84O3lPAGg1lVZIACZZpsLwaiM"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
FEED_URL   = os.environ["https://export.admitad.com/en/webmaster/websites/2948252/products/export_adv_products/?user=mosaddik_haque76762&code=zy9huf0356&template=78486&currency=INR&only_sale=true&feed_id=17677&last_import=2024.11.05.00.00"]


POSTED_FILE = "posted.txt"
FEED_FILE   = "feed.csv"

# ─────────────────────────────────────────────
#  📋  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  🤖  BOT INIT
# ─────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ─────────────────────────────────────────────
#  💾  POSTED-IDS
# ─────────────────────────────────────────────
def load_posted_ids() -> set:
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            ids = set(line.strip() for line in f if line.strip())
        log.info(f"📂  Loaded {len(ids)} posted IDs")
        return ids
    log.info("📂  No posted.txt — starting fresh")
    return set()

def save_posted_id(product_id: str) -> None:
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(product_id + "\n")

def reset_posted_ids() -> None:
    open(POSTED_FILE, "w", encoding="utf-8").close()
    log.info("🔄  All products reset — cycling from the beginning.")

posted_ids = load_posted_ids()

# ─────────────────────────────────────────────
#  🌐  FEED DOWNLOAD  (3x retry)
# ─────────────────────────────────────────────
def download_feed() -> None:
    log.info("⬇️   Downloading product feed …")
    for attempt in range(1, 4):
        try:
            r = requests.get(
                FEED_URL,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=90
            )
            r.raise_for_status()
            with open(FEED_FILE, "wb") as f:
                f.write(r.content)
            log.info(f"✅  Feed saved ({len(r.content):,} bytes)")
            return
        except Exception as e:
            log.warning(f"⚠️  Attempt {attempt}/3 failed: {e}")
            if attempt == 3:
                raise
            time.sleep(5)

# ─────────────────────────────────────────────
#  📦  LOAD & PARSE FEED
# FIX Problem 5: required columns check
# ─────────────────────────────────────────────
def load_feed() -> pd.DataFrame:
    required = {"id", "title", "link"}
    for sep in ("\t", ",", ";"):
        try:
            df = pd.read_csv(FEED_FILE, sep=sep, dtype=str, on_bad_lines="skip")
            df.columns = df.columns.str.strip().str.lower()
            # FIX Problem 5: proper required column check
            if required.issubset(set(df.columns)):
                # FIX: blank id → use row index
                df["id"] = df["id"].fillna("")
                df["id"] = df["id"].astype(str).str.strip()
                df["id"] = df["id"].replace("", pd.NA).fillna(df.index.astype(str))
                df = df.drop_duplicates(subset=["id"])
                log.info(f"📊  Feed loaded — {len(df):,} rows, sep={repr(sep)}")
                return df
        except Exception:
            continue
    raise ValueError("Could not parse feed — required columns (id, title, link) missing.")

# ─────────────────────────────────────────────
#  🧹  HELPERS
# ─────────────────────────────────────────────
def safe(val, fallback: str = "N/A") -> str:
    s = str(val).strip()
    return fallback if s in ("", "nan", "None", "NaN") else s

# FIX Problem 1: HTML escape instead of Markdown escape
def h(text: str) -> str:
    """Escape HTML special characters for Telegram HTML mode."""
    return html_lib.escape(text, quote=True)

def format_inr(raw: str) -> str:
    if raw == "N/A":
        return "N/A"
    try:
        cleaned = (
            raw.replace("USD", "").replace("INR", "")
               .replace("Rs.", "").replace("Rs", "")
               .replace("$", "").replace("₹", "")
               .replace(",", "").strip()
        )
        amount = float(cleaned)
        s = f"{amount:.0f}"
        if len(s) > 3:
            last3 = s[-3:]
            rest  = s[:-3]
            groups = []
            while len(rest) > 2:
                groups.append(rest[-2:])
                rest = rest[:-2]
            if rest:
                groups.append(rest)
            groups.reverse()
            formatted = ",".join(groups) + "," + last3
        else:
            formatted = s
        return f"₹{formatted}"
    except Exception:
        return f"₹{raw}" if raw else "N/A"

# ─────────────────────────────────────────────
#  ✉️   BUILD CAPTION  (HTML mode)
# FIX Problem 1: HTML parse_mode
# FIX Problem 4: <s> strikethrough
# ─────────────────────────────────────────────
EMOJIS = ["🔥", "⚡", "💥", "🎯", "🚀", "🌟", "💎", "🛍️"]

def build_caption(p: pd.Series) -> str:
    # All user data HTML-escaped
    # title বেশি লম্বা হলে আগেই কেটে দাও — HTML tag মাঝে কাটবে না
    title    = h(safe(p.get("title", "")))[:150]
    brand    = h(safe(p.get("brand", "")))
    category = h(safe(p.get("product_type", p.get("google_product_category", ""))))
    status   = h(safe(p.get("availability", "In Stock")))
    merchant = h(safe(p.get("merchant", p.get("advertiser", "Alibaba"))))
    # URL protocol validate করো — javascript: ইত্যাদি block
    link = safe(p.get("link", ""))
    if not link.lower().startswith(("http://", "https://")):
        link = ""

    raw_sale  = safe(p.get("sale_price", ""))
    raw_price = safe(p.get("price", ""))
    raw_final = raw_sale if raw_sale != "N/A" else raw_price
    price     = format_inr(raw_final)
    old_price = format_inr(raw_price)

    fire = random.choice(EMOJIS)

    lines = [
        f"{fire} <b>{merchant} Deal Alert!</b>",
        "",
        f"📦 {title}",
    ]

    if brand != "N/A":
        lines.append(f"🏷️ Brand: {brand}")
    if category != "N/A":
        lines.append(f"📂 {category}")

    lines.append("")

    if price != "N/A":
        lines.append(f"💰 Price: <b>{price}</b>")
        # FIX Problem 4: HTML strikethrough <s> tag
        if old_price != "N/A" and old_price != price:
            lines.append(f"<s>Was: {old_price}</s>")

    lines += [
        f"📦 Status: {status}",
        ""
    ]
    if link:
        lines.append(f'🛒 <a href="{html_lib.escape(link, quote=True)}">Buy Now ➜</a>')

    return "\n".join(lines)

# ─────────────────────────────────────────────
#  📤  POST ONE PRODUCT
# ─────────────────────────────────────────────
def post_product() -> None:
    global posted_ids

    download_feed()
    df = load_feed()

    df["id"] = df["id"].astype(str)
    available = df[~df["id"].isin(posted_ids)]
    if available.empty:
        reset_posted_ids()
        posted_ids = set()
        available  = df

    # Sequential posting
    product    = available.iloc[0]
    product_id = safe(product["id"])
    title      = safe(product.get("title", ""))
    raw_img    = safe(product.get("image_link", product.get("image", "")))
    caption    = build_caption(product)

    log.info(f"📤  Posting: {title[:60]} (id={product_id})")

    def send_text():
        bot.send_message(
            CHANNEL_ID,
            text=caption,
            parse_mode="HTML",
            disable_web_page_preview=False
        )

    try:
        if raw_img != "N/A" and raw_img.lower().startswith(("http://", "https://")):
            try:
                bot.send_photo(
                    CHANNEL_ID,
                    photo=raw_img,
                    caption=caption,
                    parse_mode="HTML"
                )
            except telebot.apihelper.ApiTelegramException as img_err:
                log.warning(f"⚠️  Photo failed ({img_err}) — text fallback")
                send_text()
        else:
            send_text()

        posted_ids.add(product_id)
        save_posted_id(product_id)
        log.info(f"✅  Posted: {title[:60]}")

    except telebot.apihelper.ApiTelegramException as e:
        log.error(f"❌  Telegram error: {e}")
        raise

# ─────────────────────────────────────────────
#  🚀  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  🚀  Admitad Bot — GitHub Actions Run")
    log.info(f"  Channel : {CHANNEL_ID}")
    log.info("=" * 50)
    try:
        post_product()
    except Exception as e:
        log.error(f"❌  Fatal: {e}", exc_info=True)
        raise SystemExit(1)