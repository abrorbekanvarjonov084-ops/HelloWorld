import asyncio
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# ============ SOZLAMALAR ============
BOT_TOKEN = "8808784995:AAFPtD79OQ31HSHk7AOfvoVYSJa5ipNbm08"      # @BotFather dan olinadi
ADMIN_ID = 8263870684                 # Sizning shaxsiy Telegram user_id raqamingiz (BOSH ADMIN)
DB_PATH = "data.db"
# =====================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Foydalanuvchining hozirgi ko'rish rejimi (shaxsiy / do'stlar) - xotirada saqlanadi
user_scope: Dict[int, str] = {}
# "Admin qo'shish" yoki "Adminlikdan olish" uchun username kutilayotgan holat
awaiting_action: Dict[int, str] = {}


# ---------- BAZA BILAN ISHLASH ----------
def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            type TEXT,
            file_id TEXT,
            file_name TEXT,
            text TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_seen TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)

    # Eski bazada "items" jadvali "file_name" ustunisiz yaratilgan bo'lishi mumkin.
    # Shu holat uchun avtomatik ravishda ustun qo'shib qo'yamiz (mavjud ma'lumotlar saqlanib qoladi).
    cur.execute("PRAGMA table_info(items)")
    existing_columns = {row[1] for row in cur.fetchall()}
    if "file_name" not in existing_columns:
        cur.execute("ALTER TABLE items ADD COLUMN file_name TEXT")

    conn.commit()
    conn.close()


def register_user(user_id: int, username: Optional[str]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, username, last_seen) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, last_seen=excluded.last_seen",
        (user_id, username, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def find_user_id_by_username(username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def add_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def save_item(user_id, username, type_, file_id=None, file_name=None, text=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (user_id, username, type, file_id, file_name, text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, type_, file_id, file_name, text, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_items(user_id=None, exclude_user_id=None, type_=None):
    conn = get_conn()
    cur = conn.cursor()
    query = ("SELECT user_id, username, type, file_id, file_name, text, created_at "
              "FROM items WHERE 1=1")
    params = []

    if user_id is not None:
        query += " AND user_id=?"
        params.append(user_id)
    if exclude_user_id is not None:
        query += " AND user_id!=?"
        params.append(exclude_user_id)

    if type_ in ("docx", "pptx", "xlsx", "pdf"):
        query += " AND type='document' AND file_name LIKE ?"
        params.append(f"%.{type_}")
    elif type_ is not None:
        query += " AND type=?"
        params.append(type_)

    query += " ORDER BY id"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- KLAVIATURA ----------
TYPE_BUTTONS = {
    "🖼 Rasm": "photo",
    "🎥 Video": "video",
    "🎵 Audio": "audio",
    "💬 Matn": "text",
    "📄 Docx": "docx",
    "📊 Pptx": "pptx",
}


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton(text="📁 Shaxsiy")]
    if is_admin(user_id):
        row1.append(KeyboardButton(text="👥 Do'stlar"))

    row2 = [KeyboardButton(text=t) for t in list(TYPE_BUTTONS.keys())[:3]]
    row3 = [KeyboardButton(text=t) for t in list(TYPE_BUTTONS.keys())[3:]]

    keyboard = [row1, row2, row3]

    if user_id == ADMIN_ID:
        keyboard.append([
            KeyboardButton(text="👤 Admin qo'shish"),
            KeyboardButton(text="🚫 Adminlikdan olish"),
        ])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# ---------- FAYL MA'LUMOTINI OLISH VA SAQLASH ----------
async def handle_media(message: Message, type_: str, file_id: str, file_name: Optional[str] = None):
    save_item(
        message.from_user.id,
        message.from_user.username,
        type_,
        file_id=file_id,
        file_name=file_name,
    )
    await message.answer("✅ Saqlandi.")


async def send_items(message: Message, rows):
    for user_id, username, type_, file_id, file_name, text, created_at in rows:
        caption = f"👤 {username or user_id} | 🕒 {created_at[:16].replace('T', ' ')}"
        if file_name:
            caption += f"\n📎 {file_name}"

        if type_ == "text":
            await message.answer(f"{caption}\n\n{text}")
        elif type_ == "photo":
            await message.answer_photo(file_id, caption=caption)
        elif type_ == "video":
            await message.answer_video(file_id, caption=caption)
        elif type_ == "document":
            await message.answer_document(file_id, caption=caption)
        elif type_ == "audio":
            await message.answer_audio(file_id, caption=caption)
        elif type_ == "animation":
            await message.answer_animation(file_id, caption=caption)
        elif type_ == "voice":
            await message.answer(caption)
            await message.answer_voice(file_id)
        elif type_ == "video_note":
            await message.answer(caption)
            await message.answer_video_note(file_id)
        elif type_ == "sticker":
            await message.answer(caption)
            await message.answer_sticker(file_id)


# ---------- /start ----------
@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Salom! Menga rasm, video, audio, ovozli xabar, stiker, gif yoki "
        "istalgan fayl (docx, pptx, pdf, txt va h.k.) yuboring — men uni saqlab qo'yaman.\n"
        "Pastdagi tugmalar orqali saqlangan ma'lumotlarni ko'rishingiz mumkin.",
        reply_markup=main_menu(message.from_user.id)
    )


# ---------- ADMIN BOSHQARUVI (faqat bosh admin ko'radi) ----------
@router.message(F.text == "👤 Admin qo'shish")
async def add_admin_prompt(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    awaiting_action[message.from_user.id] = "add_admin"
    await message.answer("Admin qilmoqchi bo'lgan foydalanuvchining username'ini yuboring (masalan: @ali123).\n"
                          "Eslatma: bu foydalanuvchi avval botga kamida bitta xabar yozgan bo'lishi kerak.")


@router.message(F.text == "🚫 Adminlikdan olish")
async def remove_admin_prompt(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    awaiting_action[message.from_user.id] = "remove_admin"
    await message.answer("Adminlikdan olinadigan foydalanuvchining username'ini yuboring (masalan: @ali123).")


@router.message(lambda m: m.from_user.id in awaiting_action)
async def awaiting_input_handler(message: Message):
    action = awaiting_action.pop(message.from_user.id)
    username = (message.text or "").strip().lstrip("@")

    if not username:
        await message.answer("Username noto'g'ri. Qaytadan urinib ko'ring.")
        return

    target_id = find_user_id_by_username(username)
    if not target_id:
        await message.answer(f"@{username} topilmadi. Bu foydalanuvchi botga hali xabar yozmagan bo'lishi mumkin.")
        return

    if action == "add_admin":
        if target_id == ADMIN_ID:
            await message.answer("Bu foydalanuvchi allaqachon bosh admin.")
        else:
            add_admin(target_id)
            await message.answer(f"✅ @{username} endi admin huquqiga ega.")
    elif action == "remove_admin":
        if target_id == ADMIN_ID:
            await message.answer("Bosh adminni olib bo'lmaydi.")
        else:
            remove_admin(target_id)
            await message.answer(f"✅ @{username} adminlikdan olindi.")


# ---------- SHAXSIY / DO'STLAR ----------
@router.message(F.text == "📁 Shaxsiy")
async def personal_handler(message: Message):
    user_scope[message.from_user.id] = "personal"
    rows = get_items(user_id=message.from_user.id)
    if not rows:
        await message.answer("Sizda hali saqlangan ma'lumot yo'q.")
        return
    await send_items(message, rows)


@router.message(F.text == "👥 Do'stlar")
async def friends_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Bu bo'lim faqat admin uchun mavjud.")
        return
    user_scope[message.from_user.id] = "friends"
    rows = get_items(exclude_user_id=message.from_user.id)
    if not rows:
        await message.answer("Boshqa foydalanuvchilardan hali ma'lumot kelmagan.")
        return
    await send_items(message, rows)


# ---------- TUR BO'YICHA FILTR (Rasm, Video, Audio, Matn, Docx, Pptx) ----------
@router.message(F.text.in_(TYPE_BUTTONS.keys()))
async def type_filter_handler(message: Message):
    type_ = TYPE_BUTTONS[message.text]
    scope = user_scope.get(message.from_user.id, "personal")

    if scope == "friends" and is_admin(message.from_user.id):
        rows = get_items(exclude_user_id=message.from_user.id, type_=type_)
    else:
        rows = get_items(user_id=message.from_user.id, type_=type_)

    if not rows:
        await message.answer("Bunday turdagi ma'lumot topilmadi.")
        return
    await send_items(message, rows)


# ---------- MEDIA SAQLASH (har biriga alohida filter - eng ishonchli usul) ----------
@router.message(F.photo)
async def h_photo(message: Message):
    await handle_media(message, "photo", message.photo[-1].file_id)


@router.message(F.video)
async def h_video(message: Message):
    await handle_media(message, "video", message.video.file_id)


@router.message(F.document)
async def h_document(message: Message):
    await handle_media(message, "document", message.document.file_id, message.document.file_name)


@router.message(F.audio)
async def h_audio(message: Message):
    await handle_media(message, "audio", message.audio.file_id, message.audio.file_name)


@router.message(F.voice)
async def h_voice(message: Message):
    await handle_media(message, "voice", message.voice.file_id)


@router.message(F.video_note)
async def h_video_note(message: Message):
    await handle_media(message, "video_note", message.video_note.file_id)


@router.message(F.animation)
async def h_animation(message: Message):
    await handle_media(message, "animation", message.animation.file_id, message.animation.file_name)


@router.message(F.sticker)
async def h_sticker(message: Message):
    await handle_media(message, "sticker", message.sticker.file_id)


# ---------- ODDIY MATN (eng oxirida - hech qaysi tugma yoki holatga to'g'ri kelmasa) ----------
@router.message(F.text)
async def text_handler(message: Message):
    save_item(message.from_user.id, message.from_user.username, "text", text=message.text)
    await message.answer("✅ Matn saqlandi.")


@dp.message.outer_middleware()
async def register_user_middleware(handler, event: Message, data):
    if event.from_user:
        register_user(event.from_user.id, event.from_user.username)
    return await handler(event, data)


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
