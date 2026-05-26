import logging
import os
import io
import asyncio
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from PIL import Image, ImageDraw, ImageFont

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')

CANVAS_SIZE = 1024

# Modes
MODE_WAIT_NAME = "wait_name"
MODE_WAIT_STYLE = "wait_style"
MODE_WAIT_COLOR = "wait_color"

# Logo styles
STYLES = [
    ("⭕ Circle Badge",     "circle"),
    ("◻️ Rounded Square",   "square"),
    ("⬡ Hexagon",          "hex"),
    ("🎯 Monogram",         "monogram"),
    ("🚩 Banner",           "banner"),
]

# Color schemes (bg, fg, accent)
COLORS = [
    ("🔵 Ocean Blue",  ((30, 144, 255),  (255, 255, 255), (15, 76, 129))),
    ("🟣 Royal Purple",((142, 68, 173),  (255, 255, 255), (74, 35, 90))),
    ("🔴 Crimson",     ((231, 76, 60),   (255, 255, 255), (115, 35, 28))),
    ("🟢 Forest",      ((39, 174, 96),   (255, 255, 255), (20, 90, 50))),
    ("🟠 Sunset",      ((230, 126, 34),  (255, 255, 255), (115, 60, 15))),
    ("⚫ Midnight",    ((30, 30, 40),    (255, 215, 0),   (200, 170, 0))),
    ("⚪ Minimal",     ((245, 245, 245), (30, 30, 30),    (100, 100, 100))),
    ("🌈 Gradient",    ("gradient",       (255, 255, 255), (0, 0, 0))),
]


# ---------- Helpers ----------

def main_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎨 Create Logo", callback_data="menu_create")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def style_markup() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(lbl, callback_data=f"sty_{key}")] for lbl, key in STYLES]
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def color_markup() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(COLORS), 2):
        row = [InlineKeyboardButton(lbl, callback_data=f"col_{i+j}")
               for j, (lbl, _) in enumerate(COLORS[i:i+2])]
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def reset_user_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ('mode', 'brand_name', 'style', 'color_idx'):
        context.user_data.pop(key, None)


def get_font(size: int, bold: bool = True):
    """Try to load a TTF font; fallback to default."""
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    candidates_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    paths = candidates_bold if bold else candidates_regular
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def get_initials(name: str) -> str:
    """Extract 1-3 letter initials from a brand name."""
    words = [w for w in name.strip().split() if w]
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(w[0] for w in words[:3]).upper()


def make_gradient_bg(size: int) -> Image.Image:
    """Create a nice diagonal gradient background."""
    img = Image.new("RGB", (size, size))
    pixels = img.load()
    c1 = (255, 94, 98)   # warm red-pink
    c2 = (102, 126, 234) # cool blue-purple
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            r = int(c1[0] * (1 - t) + c2[0] * t)
            g = int(c1[1] * (1 - t) + c2[1] * t)
            b = int(c1[2] * (1 - t) + c2[2] * t)
            pixels[x, y] = (r, g, b)
    return img


def measure_text(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[0], bbox[1]
    except Exception:
        w, h = draw.textsize(text, font=font)
        return w, h, 0, 0


# ---------- Commands ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} started the bot")
    reset_user_state(context)

    welcome = (
        "👋 *Welcome to Logo Maker Bot!*\n\n"
        "I create clean, professional logos for your brand in seconds 🎨\n\n"
        "✨ *Features:*\n"
        "• 5 styles (Circle, Square, Hexagon, Monogram, Banner)\n"
        "• 8 color schemes\n"
        "• High-res 1024×1024 PNG output\n\n"
        "Tap below to begin:"
    )
    await update.message.reply_text(welcome, reply_markup=main_menu_markup(), parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ *How to use*\n\n"
        "1. Tap 🎨 *Create Logo*\n"
        "2. Type your brand name (max 20 chars)\n"
        "3. Pick a logo style\n"
        "4. Pick a color scheme\n"
        "5. Get your logo!\n\n"
        "💡 Short names look best. For 2+ words, the first letters become a monogram.\n\n"
        "Use /cancel anytime to reset."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_menu_markup())
    else:
        await update.callback_query.edit_message_text(
            text, parse_mode='Markdown', reply_markup=main_menu_markup()
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_user_state(context)
    await update.message.reply_text(
        "❌ Cancelled. Use /start to begin again.",
        reply_markup=main_menu_markup(),
    )


# ---------- Menu callbacks ----------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_home":
        reset_user_state(context)
        await query.edit_message_text(
            "🏠 *Main Menu*\nChoose an option below:",
            reply_markup=main_menu_markup(),
            parse_mode='Markdown',
        )

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_create":
        context.user_data['mode'] = MODE_WAIT_NAME
        await query.edit_message_text(
            "🎨 *Create Logo*\n\nStep 1/3: Type your *brand name* (max 20 chars).",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")]]
            ),
        )

    elif data.startswith("sty_"):
        style = data.split("_", 1)[1]
        context.user_data['style'] = style
        context.user_data['mode'] = MODE_WAIT_COLOR
        style_name = next((lbl for lbl, k in STYLES if k == style), style)
        await query.edit_message_text(
            f"✅ Style: *{style_name}*\n\nStep 3/3: Choose a *color scheme*:",
            reply_markup=color_markup(),
            parse_mode='Markdown',
        )

    elif data.startswith("col_"):
        idx = int(data.split("_", 1)[1])
        context.user_data['color_idx'] = idx
        await do_generate(update, context)


# ---------- Text handler ----------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('mode') != MODE_WAIT_NAME:
        return

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("⚠️ Empty name. Try again or /cancel.")
        return
    if len(text) > 20:
        await update.message.reply_text("⚠️ Too long (max 20 chars). Try again or /cancel.")
        return

    context.user_data['brand_name'] = text
    context.user_data['mode'] = MODE_WAIT_STYLE
    await update.message.reply_text(
        f"📝 Brand: *{text}*\n\nStep 2/3: Pick a *style*:",
        reply_markup=style_markup(),
        parse_mode='Markdown',
    )


# ---------- Logo generation ----------

def draw_circle(canvas, draw, bg, fg, accent, text):
    if bg == "gradient":
        canvas.paste(make_gradient_bg(CANVAS_SIZE), (0, 0))
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.ellipse([60, 60, CANVAS_SIZE-60, CANVAS_SIZE-60], fill=(255, 255, 255, 230))
        canvas.paste(overlay, (0, 0), overlay)
        draw = ImageDraw.Draw(canvas)
        text_fill = (40, 40, 60)
    else:
        draw.rectangle([0, 0, CANVAS_SIZE, CANVAS_SIZE], fill=(255, 255, 255))
        # Outer ring (accent)
        draw.ellipse([40, 40, CANVAS_SIZE-40, CANVAS_SIZE-40], fill=accent)
        # Inner circle
        draw.ellipse([80, 80, CANVAS_SIZE-80, CANVAS_SIZE-80], fill=bg)
        text_fill = fg

    initials = get_initials(text)
    font = get_font(int(CANVAS_SIZE * 0.35))
    tw, th, ox, oy = measure_text(draw, initials, font)
    x = (CANVAS_SIZE - tw) // 2 - ox
    y = (CANVAS_SIZE - th) // 2 - oy - 20
    draw.text((x, y), initials, font=font, fill=text_fill)


def draw_square(canvas, draw, bg, fg, accent, text):
    if bg == "gradient":
        canvas.paste(make_gradient_bg(CANVAS_SIZE), (0, 0))
        text_fill = (255, 255, 255)
    else:
        draw.rectangle([0, 0, CANVAS_SIZE, CANVAS_SIZE], fill=(255, 255, 255))
        # Rounded square
        draw.rounded_rectangle([60, 60, CANVAS_SIZE-60, CANVAS_SIZE-60],
                               radius=80, fill=bg, outline=accent, width=8)
        text_fill = fg

    display_text = text if len(text) <= 8 else get_initials(text)
    font_size = int(CANVAS_SIZE * 0.18) if len(display_text) > 4 else int(CANVAS_SIZE * 0.28)
    font = get_font(font_size)
    tw, th, ox, oy = measure_text(draw, display_text, font)
    x = (CANVAS_SIZE - tw) // 2 - ox
    y = (CANVAS_SIZE - th) // 2 - oy - 20
    draw.text((x, y), display_text, font=font, fill=text_fill)


def draw_hexagon(canvas, draw, bg, fg, accent, text):
    import math
    if bg == "gradient":
        canvas.paste(make_gradient_bg(CANVAS_SIZE), (0, 0))
        text_fill = (255, 255, 255)
        bg_to_use = (255, 255, 255)
    else:
        draw.rectangle([0, 0, CANVAS_SIZE, CANVAS_SIZE], fill=(255, 255, 255))
        text_fill = fg
        bg_to_use = bg

    cx, cy = CANVAS_SIZE / 2, CANVAS_SIZE / 2
    r = CANVAS_SIZE * 0.42
    # Outer hex (accent)
    outer = [(cx + (r+15) * math.cos(math.pi/3 * i - math.pi/6),
              cy + (r+15) * math.sin(math.pi/3 * i - math.pi/6)) for i in range(6)]
    draw.polygon(outer, fill=accent if bg != "gradient" else (255,255,255,255))
    # Inner hex
    inner = [(cx + r * math.cos(math.pi/3 * i - math.pi/6),
              cy + r * math.sin(math.pi/3 * i - math.pi/6)) for i in range(6)]
    draw.polygon(inner, fill=bg_to_use if bg != "gradient" else (50, 50, 70))

    initials = get_initials(text)
    font = get_font(int(CANVAS_SIZE * 0.3))
    tw, th, ox, oy = measure_text(draw, initials, font)
    x = (CANVAS_SIZE - tw) // 2 - ox
    y = (CANVAS_SIZE - th) // 2 - oy - 20
    draw.text((x, y), initials, font=font, fill=text_fill if bg != "gradient" else (255, 255, 255))


def draw_monogram(canvas, draw, bg, fg, accent, text):
    if bg == "gradient":
        canvas.paste(make_gradient_bg(CANVAS_SIZE), (0, 0))
        text_fill = (255, 255, 255)
        line_color = (255, 255, 255)
    else:
        draw.rectangle([0, 0, CANVAS_SIZE, CANVAS_SIZE], fill=bg)
        text_fill = fg
        line_color = fg

    initials = get_initials(text)
    font = get_font(int(CANVAS_SIZE * 0.5), bold=True)
    tw, th, ox, oy = measure_text(draw, initials, font)
    x = (CANVAS_SIZE - tw) // 2 - ox
    y = (CANVAS_SIZE - th) // 2 - oy - 40
    draw.text((x, y), initials, font=font, fill=text_fill)

    # Decorative line above and below
    line_w = int(CANVAS_SIZE * 0.45)
    draw.rectangle([(CANVAS_SIZE - line_w) // 2, y - 30,
                    (CANVAS_SIZE + line_w) // 2, y - 22], fill=line_color)
    draw.rectangle([(CANVAS_SIZE - line_w) // 2, y + th + 30,
                    (CANVAS_SIZE + line_w) // 2, y + th + 38], fill=line_color)


def draw_banner(canvas, draw, bg, fg, accent, text):
    if bg == "gradient":
        canvas.paste(make_gradient_bg(CANVAS_SIZE), (0, 0))
        text_fill = (255, 255, 255)
        accent_color = (255, 255, 255)
    else:
        draw.rectangle([0, 0, CANVAS_SIZE, CANVAS_SIZE], fill=(255, 255, 255))
        # Banner stripe
        draw.rectangle([0, int(CANVAS_SIZE * 0.32),
                        CANVAS_SIZE, int(CANVAS_SIZE * 0.68)], fill=bg)
        # Accent stripes
        draw.rectangle([0, int(CANVAS_SIZE * 0.28),
                        CANVAS_SIZE, int(CANVAS_SIZE * 0.32)], fill=accent)
        draw.rectangle([0, int(CANVAS_SIZE * 0.68),
                        CANVAS_SIZE, int(CANVAS_SIZE * 0.72)], fill=accent)
        text_fill = fg
        accent_color = accent

    display_text = text.upper()
    # Auto-fit font size
    font_size = int(CANVAS_SIZE * 0.18)
    while font_size > 30:
        font = get_font(font_size)
        tw, th, _, _ = measure_text(draw, display_text, font)
        if tw < CANVAS_SIZE * 0.85:
            break
        font_size -= 8
    else:
        font = get_font(30)
        tw, th, _, _ = measure_text(draw, display_text, font)

    x = (CANVAS_SIZE - tw) // 2
    y = (CANVAS_SIZE - th) // 2 - 20
    draw.text((x, y), display_text, font=font, fill=text_fill)


def generate_logo(name: str, style: str, color_idx: int) -> bytes:
    _, scheme = COLORS[color_idx]
    bg, fg, accent = scheme

    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    if style == "circle":
        draw_circle(canvas, draw, bg, fg, accent, name)
    elif style == "square":
        draw_square(canvas, draw, bg, fg, accent, name)
    elif style == "hex":
        draw_hexagon(canvas, draw, bg, fg, accent, name)
    elif style == "monogram":
        draw_monogram(canvas, draw, bg, fg, accent, name)
    elif style == "banner":
        draw_banner(canvas, draw, bg, fg, accent, name)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def do_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    name = context.user_data.get('brand_name')
    style = context.user_data.get('style')
    color_idx = context.user_data.get('color_idx')

    if not name or not style or color_idx is None:
        await query.edit_message_text("⚠️ Missing data. Start again.", reply_markup=main_menu_markup())
        return

    chat_id = query.message.chat_id
    await query.edit_message_text("⏳ Generating your logo…")

    try:
        loop = asyncio.get_event_loop()
        out_bytes = await loop.run_in_executor(
            None, generate_logo, name, style, color_idx
        )

        safe_name = "".join(c for c in name if c.isalnum() or c in "_-") or "logo"
        out_name = f"{safe_name}_logo.png"

        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(io.BytesIO(out_bytes), filename=out_name),
            caption=f"✅ *Your logo is ready!*\n\nBrand: *{name}*\nResolution: 1024×1024",
            parse_mode='Markdown',
            reply_markup=main_menu_markup(),
        )

    except Exception as e:
        logger.error(f"Logo generation failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Failed: {e}",
            reply_markup=main_menu_markup(),
        )
    finally:
        reset_user_state(context)


# ---------- Dummy web server (keeps Render Web Service alive) ----------

async def health(request):
    return web.Response(text="Bot is running")


async def run_web():
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server listening on port {port}")


# ---------- Runner ----------

async def run_bot():
    if not BOT_TOKEN:
        logger.critical("FATAL: BOT_TOKEN is missing!")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CallbackQueryHandler(menu_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

        await run_web()

        logger.info("Bot is now polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        stop_event = asyncio.Event()
        await stop_event.wait()

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    finally:
        if 'application' in locals():
            await application.stop()
            await application.shutdown()


def main():
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Main loop error: {e}")


if __name__ == '__main__':
    main()
