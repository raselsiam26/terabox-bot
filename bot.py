import os
import re
import asyncio
import logging
import requests
from urllib.parse import urlparse, parse_qs

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode, ChatAction

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

TERABOX_DOMAINS = [
    "terabox.com", "teraboxapp.com", "www.terabox.com",
    "1024terabox.com", "teraboxlink.com", "terabox.app",
    "mirrobox.com", "nephobox.com", "freeterabox.com",
    "www.1024tera.com", "4funbox.co", "tibibox.com",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.terabox.com/",
}


def is_terabox_link(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d.lstrip("www.") for d in TERABOX_DOMAINS)
    except Exception:
        return False


def _is_video_file(name: str) -> bool:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in {"mp4", "mkv", "avi", "mov", "webm", "flv", "m4v", "ts", "3gp"}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fetch_terabox_direct(share_url: str) -> dict:
    """
    Try two resolvers in sequence to get a direct streaming URL from a Terabox share link.
    """
    # ── Resolver 1: terabox.udayscriptsx.workers.dev ──────────────────────────
    proxy = f"https://terabox.udayscriptsx.workers.dev/?url={share_url}"
    try:
        resp = requests.get(proxy, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            direct_url = data.get("direct_url") or data.get("download_url") or ""
            if direct_url:
                return {
                    "title":        data.get("title") or "Video",
                    "thumbnail":    data.get("thumbnail"),
                    "direct_url":   direct_url,
                    "download_url": direct_url,
                    "size":         data.get("size") or "অজানা",
                    "is_video":     _is_video_file(data.get("title") or ""),
                }
    except Exception as e:
        logger.warning("Resolver 1 failed: %s", e)

    # ── Resolver 2: teraboxapp.com shorturlinfo ────────────────────────────────
    try:
        api_url = f"https://teraboxapp.com/api/shorturlinfo?shorturl={share_url}"
        resp = requests.get(api_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        file_list = data.get("list", [])
        if file_list:
            item       = file_list[0]
            title      = item.get("server_filename") or item.get("filename") or "Video"
            thumbnail  = (item.get("thumbs") or {}).get("url3") or (item.get("thumbs") or {}).get("url1")
            direct_url = item.get("dlink") or item.get("download_link") or ""
            size_bytes = int(item.get("size", 0))
            if direct_url:
                return {
                    "title":        title,
                    "thumbnail":    thumbnail,
                    "direct_url":   direct_url,
                    "download_url": direct_url,
                    "size":         _human_size(size_bytes),
                    "is_video":     _is_video_file(title),
                }
    except Exception as e:
        logger.warning("Resolver 2 failed: %s", e)

    raise ValueError(
        "লিংকটি resolve করা যায়নি।\n"
        "• লিংকটি সঠিক কিনা চেক করুন\n"
        "• লিংকটি publicly shared কিনা নিশ্চিত করুন\n"
        "• কিছুক্ষণ পরে আবার চেষ্টা করুন"
    )


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *স্বাগতম Terabox Bot-এ!*\n\n"
        "যেকোনো *Terabox শেয়ার লিংক* পাঠান।\n"
        "আমি সরাসরি টেলিগ্রামে ভিডিও স্ট্রিমিং লিংক দিয়ে দেব — "
        "আলাদা করে Terabox খুলতে হবে না! 🎬\n\n"
        "উদাহরণ:\n"
        "`https://terabox.com/s/xxxxxxxx`\n\n"
        "/help — সাহায্য",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *কিভাবে ব্যবহার করবেন:*\n\n"
        "১. Terabox-এ কোনো ভিডিওর শেয়ার লিংক কপি করুন\n"
        "২. এই বটে পেস্ট করে পাঠান\n"
        "৩. বট ডিরেক্ট স্ট্রিমিং ও ডাউনলোড লিংক দেবে ✅\n\n"
        "*সাপোর্টেড ডোমেইন:*\n"
        "`terabox.com` · `teraboxapp.com` · `1024terabox.com`\n"
        "`mirrobox.com` · `nephobox.com` · `freeterabox.com` · এবং আরও",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        await update.message.reply_text(
            "⚠️ কোনো লিংক পাইনি।\nএকটি Terabox শেয়ার লিংক পাঠান।"
        )
        return

    url = url_match.group(0).rstrip(")")  # clean trailing bracket if any

    if not is_terabox_link(url):
        await update.message.reply_text(
            "❌ এটি Terabox লিংক মনে হচ্ছে না।\n"
            "অনুগ্রহ করে একটি সঠিক Terabox শেয়ার লিংক পাঠান।"
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    processing_msg = await update.message.reply_text("⏳ লিংক প্রসেস হচ্ছে, একটু অপেক্ষা করুন...")

    try:
        info = await asyncio.get_event_loop().run_in_executor(
            None, fetch_terabox_direct, url
        )
    except ValueError as exc:
        await processing_msg.edit_text(
            f"❌ *সমস্যা হয়েছে:*\n{exc}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    except Exception:
        logger.exception("Unexpected error resolving %s", url)
        await processing_msg.edit_text(
            "❌ অপ্রত্যাশিত সমস্যা হয়েছে। পরে আবার চেষ্টা করুন।"
        )
        return

    direct = info["direct_url"]
    title  = info["title"]
    size   = info["size"]
    is_vid = info["is_video"]
    thumb  = info.get("thumbnail")
    emoji  = "🎬" if is_vid else "📁"

    caption = (
        f"{emoji} *{title}*\n"
        f"📦 সাইজ: `{size}`\n\n"
        "▶️ Stream বাটনে ক্লিক করলে সরাসরি ব্রাউজারে চলবে।\n"
        "⬇️ Download বাটন দিয়ে সেভ করতে পারবেন।"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Stream / Watch", url=direct),
            InlineKeyboardButton("⬇️ Download", url=direct),
        ],
    ])

    await processing_msg.delete()

    if thumb:
        try:
            await update.message.reply_photo(
                photo=thumb,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass  # thumbnail fetch failed, fall through

    await update.message.reply_text(
        caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Update %s caused error: %s", update, ctx.error)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "\n⚠️  BOT_TOKEN পাওয়া যায়নি!\n"
            "চালানোর আগে environment variable সেট করুন:\n"
            "  Linux/Mac:  export BOT_TOKEN=your_token_here\n"
            "  Windows:    set BOT_TOKEN=your_token_here\n"
        )

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("✅ Terabox Bot চালু হয়েছে...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
