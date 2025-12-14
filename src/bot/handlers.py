import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from bot import keyboards, texts
from bot.states import GiftStates
from config.logger import log_extra
from config.settings import Settings
from db.database import Database

CURRENCY = "XTR"
PAGE_SIZE = 20

logger = logging.getLogger(__name__)


def setup_handlers(router: Router, db: Database, settings: Settings) -> None:
    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await db.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(texts.WELCOME, reply_markup=keyboards.main_menu())

    @router.callback_query(F.data == "menu:root")
    async def menu_root(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        if callback.message:
            await safe_edit(callback.message, texts.WELCOME, keyboards.main_menu())

    @router.callback_query(F.data == "menu:buy")
    async def menu_buy(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await safe_edit(callback.message, "Выберите пакет Stars для оплаты:", keyboards.buy_packs_keyboard())

    @router.callback_query(F.data == "menu:gift")
    async def menu_gift(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.set_state(GiftStates.waiting_for_recipient)
        await state.update_data(sender_id=callback.from_user.id)
        text = (
            "Введите @username или user_id получателя.\n"
            "Пример: @username или 123456789. Отправка возможна только внутри бота."
        )
        if callback.message:
            await safe_edit(callback.message, text, keyboards.main_menu())

    @router.callback_query(F.data.startswith("menu:history:"))
    async def menu_history(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        try:
            page = int(parts[-1]) if len(parts) == 3 else 0
        except ValueError:
            page = 0
        page = max(page, 0)
        await send_history(callback, db, page)

    @router.callback_query(F.data == "menu:help")
    async def menu_help(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await safe_edit(callback.message, texts.HELP, keyboards.main_menu())

    @router.callback_query(F.data == "menu:balance")
    async def menu_balance(callback: CallbackQuery) -> None:
        await callback.answer()
        bal = await db.get_balance(callback.from_user.id)
        if callback.message:
            await safe_edit(callback.message, texts.balance_text(callback.from_user.id, bal), keyboards.main_menu())

    @router.message(GiftStates.waiting_for_recipient)
    async def gift_recipient(message: Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        recipient_id = parse_user_ref(raw)
        if recipient_id is None:
            await message.answer("Не смог понять пользователя. Укажите @username или числовой user_id.")
            return
        if recipient_id == message.from_user.id:
            await message.answer("Нельзя отправить Stars самому себе.")
            return
        await state.clear()
        await db.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(
            f"Получатель: <code>{recipient_id}</code>\nВыберите сумму подарка:",
            reply_markup=keyboards.gift_amount_keyboard(recipient_id),
        )

    @router.callback_query(F.data.startswith("gift:"))
    async def gift_amount(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Некорректная команда", show_alert=True)
            return
        recipient_id, amount = int(parts[1]), int(parts[2])
        sender_id = callback.from_user.id
        if recipient_id == sender_id:
            await callback.answer("Нельзя отправить Stars самому себе", show_alert=True)
            return

        balance = await db.get_balance(sender_id)
        if balance < amount:
            await callback.answer("Недостаточно Stars на балансе бота.", show_alert=True)
            return
        try:
            await db.transfer(
                from_user=sender_id,
                to_user=recipient_id,
                amount=amount,
                from_username=callback.from_user.username,
                to_username=None,
            )
        except ValueError as exc:
            logger.warning("transfer failed", extra=log_extra(error=str(exc)))
            await callback.answer("Не удалось выполнить перевод. Попробуйте позже.", show_alert=True)
            return

        new_balance = await db.get_balance(sender_id)
        if callback.message:
            await callback.message.edit_text(
                f"Готово! Отправлено {amount}⭐ пользователю <code>{recipient_id}</code>.\n"
                f"Ваш баланс в боте: {new_balance}⭐",
                reply_markup=keyboards.main_menu(),
            )

    @router.callback_query(F.data.startswith("refund:"))
    async def refund(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            amount = int(callback.data.split(":")[1])
        except (ValueError, IndexError):
            await callback.answer("Некорректная сумма", show_alert=True)
            return

        user_id = callback.from_user.id
        payment = await db.get_payment_for_amount(user_id, amount)
        if not payment:
            await callback.answer("Нет подходящих платежей для возврата.", show_alert=True)
            return

        try:
            ok = await callback.bot.refund_star_payment(
                user_id=user_id, telegram_payment_charge_id=payment["charge_id"]
            )
        except Exception as exc:  # pragma: no cover - Telegram failure
            logger.error("refund failed", extra=log_extra(error=str(exc), user_id=user_id))
            await callback.answer("Не удалось выполнить возврат сейчас. Попробуйте позже.", show_alert=True)
            return

        if not ok:
            await callback.answer("Telegram отказал в возврате.", show_alert=True)
            return

        success = await db.mark_refund(user_id=user_id, charge_id=payment["charge_id"], amount=amount)
        if not success:
            await callback.answer("Не удалось отметить возврат в базе.", show_alert=True)
            return

        balance = await db.get_balance(user_id)
        if callback.message:
            await callback.message.edit_text(
                f"Возврат {amount}⭐ выполнен.\nТекущий баланс в боте: {balance}⭐",
                reply_markup=keyboards.main_menu(),
            )

    @router.callback_query(F.data.startswith("buy:"))
    async def buy_stars(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            amount = int(callback.data.split(":")[1])
        except (ValueError, IndexError):
            await callback.answer("Некорректная сумма", show_alert=True)
            return
        if amount not in keyboards.BUY_PACKS:
            await callback.answer("Сумма недоступна", show_alert=True)
            return

        payload = f"buy:{amount}:{callback.from_user.id}"
        prices = [LabeledPrice(label=f"{amount} Stars", amount=amount)]
        try:
            await callback.bot.send_invoice(
                chat_id=callback.from_user.id,
                title=f"Покупка {amount}⭐",
                description="Оплата Stars внутри Telegram",
                payload=payload,
                provider_token="",
                currency=CURRENCY,
                prices=prices,
                start_parameter="stars",
            )
        except TelegramBadRequest as exc:
            logger.error("failed to send invoice", extra=log_extra(error=str(exc)))
            await callback.answer("Не удалось создать счёт. Попробуйте позже.", show_alert=True)

    @router.pre_checkout_query()
    async def pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
        if pre_checkout_query.currency != CURRENCY:
            await pre_checkout_query.answer(ok=False, error_message="Требуется валюта XTR (Stars).")
            return
        payload = pre_checkout_query.invoice_payload or ""
        parts = payload.split(":")
        if len(parts) != 3 or parts[0] != "buy":
            await pre_checkout_query.answer(ok=False, error_message="Некорректный payload.")
            return
        amount = int(parts[1])
        user_from_payload = int(parts[2])
        if amount != pre_checkout_query.total_amount or user_from_payload != pre_checkout_query.from_user.id:
            await pre_checkout_query.answer(ok=False, error_message="Проверка суммы не пройдена.")
            return
        if amount not in keyboards.BUY_PACKS:
            await pre_checkout_query.answer(ok=False, error_message="Некорректная сумма.")
            return
        await pre_checkout_query.answer(ok=True)

    @router.message(F.successful_payment)
    async def successful_payment(message: Message) -> None:
        payment = message.successful_payment
        if not payment or payment.currency != CURRENCY:
            return
        user_id = message.from_user.id
        amount = payment.total_amount
        charge_id = payment.telegram_payment_charge_id

        created = await db.add_purchase(user_id, message.from_user.username, amount, charge_id)
        if not created:
            await message.answer("Этот платёж уже обработан.")
            return

        balance = await db.get_balance(user_id)
        await message.answer(
            f"Покупка успешна! +{amount}⭐ зачислено на баланс.\nВаш баланс в боте: {balance}⭐",
            reply_markup=keyboards.main_menu(),
        )
        logger.info(
            "purchase completed",
            extra=log_extra(user_id=user_id, amount=amount, charge_id=charge_id),
        )

    @router.callback_query(F.data == "noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()


async def send_history(callback: CallbackQuery, db: Database, page: int) -> None:
    offset = page * PAGE_SIZE
    items = await db.get_transactions(callback.from_user.id, limit=PAGE_SIZE, offset=offset)
    total = await db.count_transactions(callback.from_user.id)
    has_prev = page > 0
    has_next = offset + PAGE_SIZE < total

    refundable: list[int] = []
    for amount in keyboards.BUY_PACKS:
        payment = await db.get_payment_for_amount(callback.from_user.id, amount)
        if payment and amount not in refundable:
            refundable.append(amount)

    if not items:
        text = "История пуста. Совершите покупку или перевод, чтобы увидеть операции."
    else:
        lines = [texts.history_entry(item) for item in items]
        text = "🧾 История операций (последние):\n\n" + "\n\n".join(lines)

    if callback.message:
        try:
            await callback.message.edit_text(
                text, reply_markup=keyboards.history_keyboard(page, has_prev, has_next, refundable)
            )
        except TelegramBadRequest:
            await callback.message.answer(
                text, reply_markup=keyboards.history_keyboard(page, has_prev, has_next, refundable)
            )


def parse_user_ref(raw: str) -> Optional[int]:
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if raw.isdigit():
        return int(raw)
    return None


async def safe_edit(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup)
