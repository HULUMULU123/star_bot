import asyncio
import logging
import os
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")


BUY_AMOUNTS = (50, 100, 250, 500)
SELL_AMOUNTS = (50, 100, 250)
user_balances: Dict[int, int] = {}


def build_main_keyboard() -> InlineKeyboardMarkup:
    buy_buttons = [
        InlineKeyboardButton(text=f"Купить {amount}⭐", callback_data=f"buy:{amount}")
        for amount in BUY_AMOUNTS
    ]
    sell_buttons = [
        InlineKeyboardButton(text=f"Продать {amount}⭐", callback_data=f"sell:{amount}")
        for amount in SELL_AMOUNTS
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buy_buttons[:2],
            buy_buttons[2:],
            sell_buttons[:2],
            sell_buttons[2:],
            [InlineKeyboardButton(text="Баланс", callback_data="balance")],
        ]
    )


def get_balance(user_id: int) -> int:
    return user_balances.get(user_id, 0)


def set_balance(user_id: int, balance: int) -> None:
    user_balances[user_id] = max(balance, 0)


async def handle_start(message: Message) -> None:
    keyboard = build_main_keyboard()
    await message.answer(
        "Привет! Я бот для покупки и продажи ⭐.",
        reply_markup=keyboard,
    )


async def handle_balance(callback: CallbackQuery) -> None:
    balance = get_balance(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        f"На вашем счёте {balance}⭐.", reply_markup=build_main_keyboard()
    )


async def handle_buy(callback: CallbackQuery, amount: int) -> None:
    await callback.answer()
    payload = f"buy:{amount}:{callback.from_user.id}"
    prices = [LabeledPrice(label=f"Покупка {amount}⭐", amount=amount)]
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Покупка {amount}⭐",
        description="Моментальная покупка звёзд",
        payload=payload,
        provider_token="STARS",
        currency="XTR",
        prices=prices,
        start_parameter=payload,
    )


async def handle_sell(callback: CallbackQuery, amount: int) -> None:
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    if balance < amount:
        await callback.answer("Недостаточно звёзд на балансе", show_alert=True)
        return

    set_balance(user_id, balance - amount)
    await callback.answer()
    await callback.message.edit_text(
        f"Вы продали {amount}⭐. Остаток {get_balance(user_id)}⭐.",
        reply_markup=build_main_keyboard(),
    )


async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


async def handle_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    user_id = message.from_user.id
    stars = payment.total_amount
    balance = get_balance(user_id)
    set_balance(user_id, balance + stars)
    await message.answer(
        f"Платёж на {stars}⭐ успешно получен! Текущий баланс: {get_balance(user_id)}⭐",
        reply_markup=build_main_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def handle_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    if data == "balance":
        await handle_balance(callback)
        return

    action, _, value = data.partition(":")
    if not value:
        await callback.answer("Некорректная команда", show_alert=True)
        return

    try:
        amount = int(value)
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return

    if action == "buy":
        await handle_buy(callback, amount)
    elif action == "sell":
        await handle_sell(callback, amount)
    else:
        await callback.answer("Неизвестное действие", show_alert=True)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    dp.message.register(handle_start, CommandStart())
    dp.callback_query.register(handle_callback, F.data)
    dp.pre_checkout_query.register(handle_pre_checkout)
    dp.message.register(handle_successful_payment, F.successful_payment)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot is up and running")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
