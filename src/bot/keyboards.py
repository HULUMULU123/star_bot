from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BUY_PACKS = [50, 100, 250, 500]


def main_menu(include_test: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ Купить Stars", callback_data="menu:buy"),
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Подарить Stars", callback_data="menu:gift"),
    )
    builder.row(
        InlineKeyboardButton(text="💳 Мой баланс", callback_data="menu:balance"),
    )
    builder.row(
        InlineKeyboardButton(text="🧾 История", callback_data="menu:history:0"),
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ Помощь", callback_data="menu:help"),
    )
    if include_test:
        builder.row(
            InlineKeyboardButton(text="🧪 Тест: +50⭐", callback_data="test:add50"),
        )
    return builder.as_markup()


def buy_packs_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for amount in BUY_PACKS:
        builder.button(text=f"+{amount} ⭐", callback_data=f"buy:{amount}")
    builder.button(text="⬅️ Назад", callback_data="menu:root")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def gift_amount_keyboard(recipient_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for amount in BUY_PACKS:
        builder.button(text=f"Отправить {amount} ⭐", callback_data=f"gift:{recipient_id}:{amount}")
    builder.button(text="⬅️ Назад", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def history_keyboard(page: int, has_prev: bool, has_next: bool, refund_amounts: list[int] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_prev:
        builder.button(text="←", callback_data=f"menu:history:{page-1}")
    builder.button(text=f"Стр. {page+1}", callback_data="noop")
    if has_next:
        builder.button(text="→", callback_data=f"menu:history:{page+1}")
    if refund_amounts:
        for amount in refund_amounts:
            builder.button(text=f"↩️ Вернуть {amount}⭐", callback_data=f"refund:{amount}")
    builder.button(text="⬅️ Назад", callback_data="menu:root")
    builder.adjust(3, 1, 1)
    return builder.as_markup()
