import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import load_config
from db import Database

logging.basicConfig(level=logging.INFO)
router = Router()
config = load_config()
db = Database(config.database_path)


def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔗 Моя реферальная ссылка", callback_data="my_link")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="📣 Вступить в канал", callback_data="join_channel")],
    ]
    if user_id == config.admin_id:
        rows.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🏆 Топ рефереров", callback_data="admin_top")],
        [InlineKeyboardButton(text="📥 Выгрузить CSV", callback_data="admin_export")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="home")],
    ])


def parse_inviter(args: str | None) -> int | None:
    if not args or not args.startswith("ref_"):
        return None
    value = args.removeprefix("ref_")
    return int(value) if value.isdigit() else None


async def referral_link(bot: Bot, user_id: int) -> str:
    me = await bot.get_me()
    return "https://t.me/" + str(me.username) + "?start=ref_" + str(user_id)


async def register(message: Message, inviter_id: int | None = None) -> None:
    user = message.from_user
    if user:
        await db.register_user(user.id, user.username, user.full_name, inviter_id)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject) -> None:
    inviter_id = parse_inviter(command.args)
    await register(message, inviter_id)
    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Получите персональную ссылку, приглашайте друзей и следите за статистикой. "
        "Реферал засчитывается после реального вступления в канал.",
        reply_markup=main_keyboard(message.from_user.id),
    )


@router.message(Command("myref"))
async def myref_command(message: Message, bot: Bot) -> None:
    await register(message)
    link = await referral_link(bot, message.from_user.id)
    await message.answer(
        f"Ваша персональная ссылка:\n<code>{link}</code>\n\n"
        "Отправьте её друзьям."
    )


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if message.from_user.id != config.admin_id:
        await message.answer("⛔️ Нет доступа.")
        return
    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_keyboard())


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Главное меню:", reply_markup=main_keyboard(callback.from_user.id)
    )
    await callback.answer()


@router.callback_query(F.data == "my_link")
async def my_link(callback: CallbackQuery, bot: Bot) -> None:
    await db.register_user(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name,
        None,
    )
    link = await referral_link(bot, callback.from_user.id)
    await callback.message.answer(
        f"🔗 <b>Ваша персональная ссылка</b>\n<code>{link}</code>\n\n"
        "Реферал будет засчитан после вступления в канал."
    )
    await callback.answer()


@router.callback_query(F.data == "my_stats")
async def my_stats(callback: CallbackQuery) -> None:
    leads, joined = await db.referral_stats(callback.from_user.id)
    await callback.message.answer(
        "📊 <b>Ваша статистика</b>\n\n"
        f"Перешли в бота: <b>{leads}</b>\n"
        f"Вступили в канал: <b>{joined}</b>"
    )
    await callback.answer()


@router.callback_query(F.data == "join_channel")
async def join_channel(callback: CallbackQuery, bot: Bot) -> None:
    user_id = callback.from_user.id
    try:
        member = await bot.get_chat_member(config.channel_id, user_id)
        if member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }:
            inviter_id, changed = await db.mark_joined(user_id)
            await callback.answer("Вы уже состоите в канале ✅", show_alert=True)
            if changed and inviter_id:
                try:
                    await bot.send_message(inviter_id, "🎉 По вашей ссылке вступил новый участник!")
                except Exception:
                    logging.exception("Не удалось уведомить реферера")
            return

        invite = await bot.create_chat_invite_link(
            chat_id=config.channel_id,
            name=f"user-{user_id}",
            expire_date=datetime.now(timezone.utc) + timedelta(days=1),
            creates_join_request=True,
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Отправить заявку", url=invite.invite_link)],
        ])
        await callback.message.answer(
            "Нажмите кнопку ниже. Бот автоматически примет заявку и засчитает вступление.",
            reply_markup=keyboard,
        )
        await callback.answer()
    except Exception:
        logging.exception("Ошибка создания ссылки на канал")
        await callback.answer(
            "Не удалось создать ссылку. Проверьте права бота в канале.",
            show_alert=True,
        )


@router.chat_join_request()
async def join_request(event: ChatJoinRequest, bot: Bot) -> None:
    if str(event.chat.id) != str(config.channel_id):
        return
    try:
        await bot.approve_chat_join_request(event.chat.id, event.from_user.id)
        inviter_id, changed = await db.mark_joined(event.from_user.id)
        if changed:
            try:
                await bot.send_message(event.from_user.id, "✅ Ваша заявка принята, вступление засчитано!")
            except Exception:
                logging.exception("Не удалось уведомить вступившего")
            if inviter_id:
                try:
                    await bot.send_message(inviter_id, "🎉 По вашей ссылке вступил новый участник!")
                except Exception:
                    logging.exception("Не удалось уведомить реферера")
    except Exception:
        logging.exception("Не удалось обработать заявку на вступление")


def is_admin(callback: CallbackQuery) -> bool:
    return callback.from_user.id == config.admin_id


@router.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery) -> None:
    if not is_admin(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text("⚙️ <b>Админ-панель</b>", reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    users, joined, referrers = await db.global_stats()
    await callback.message.answer(
        "📊 <b>Общая статистика</b>\n\n"
        f"Пользователей бота: <b>{users}</b>\n"
        f"Вступили в канал: <b>{joined}</b>\n"
        f"Активных рефереров: <b>{referrers}</b>"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_top")
async def admin_top(callback: CallbackQuery) -> None:
    if not is_admin(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rows = await db.top_referrers()
    if not rows:
        text = "Пока нет рефералов."
    else:
        lines = ["🏆 <b>Топ рефереров</b>\n"]
        for number, (user_id, username, full_name, leads, joined) in enumerate(rows, 1):
            label = f"@{username}" if username else full_name
            lines.append(f"{number}. {label} — <b>{joined}</b> вступили / {leads} перешли")
        text = "\n".join(lines)
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "admin_export")
async def admin_export(callback: CallbackQuery) -> None:
    if not is_admin(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rows = await db.all_users()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "full_name", "inviter_id", "joined", "created_at", "joined_at"])
    writer.writerows(rows)
    file = BufferedInputFile(output.getvalue().encode("utf-8-sig"), filename="referral_users.csv")
    await callback.message.answer_document(file, caption="Выгрузка пользователей")
    await callback.answer()


async def main() -> None:
    await db.init()
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
