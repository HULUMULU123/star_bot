WELCOME = (
    "Привет! Я бот для работы со Stars внутри приложения.\n\n"
    "Что я умею:\n"
    "• Купить пакеты Stars и пополнить внутренний баланс\n"
    "• Подарить Stars другому пользователю\n"
    "• Показать баланс и историю операций\n\n"
    "Баланс хранится только внутри бота, это не официальный баланс Telegram."
)

HELP = (
    "ℹ️ Помощь\n\n"
    "• Покупка Stars: выберите пакет и оплатите через Telegram Stars (XTR).\n"
    "• Подарок: укажите @username или user_id получателя и выберите сумму.\n"
    "• Баланс и история: показывают данные только внутри этого бота.\n"
    "• Возврат Stars доступен, если Telegram разрешает refund для платежа."
)


def balance_text(user_id: int, balance: int) -> str:
    return f"💳 Баланс в боте: {balance}⭐\nВаш user_id: <code>{user_id}</code>"


def history_entry(row: dict) -> str:
    emoji = {
        "purchase": "🟢",
        "gift_in": "🎁",
        "gift_out": "📤",
        "refund": "↩️",
    }.get(row["type"], "•")
    direction = {
        "purchase": "+",
        "gift_in": "+",
        "gift_out": "-",
        "refund": "-",
    }.get(row["type"], "")
    amount = row["amount"]
    related = row.get("related_user_id")
    related_text = f" | Контрагент: {related}" if related else ""
    desc = row.get("description") or ""
    return f"{emoji} {direction}{amount}⭐ ({row['type']}){related_text}\n{desc}\n{row['created_at']}"
