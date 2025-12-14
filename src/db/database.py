from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    charge_id TEXT NOT NULL UNIQUE,
    refunded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(from_user_id) REFERENCES users(user_id),
    FOREIGN KEY(to_user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('purchase', 'gift_in', 'gift_out', 'refund')),
    amount INTEGER NOT NULL,
    related_user_id INTEGER,
    charge_id TEXT,
    description TEXT,
    balance_after INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(related_user_id) REFERENCES users(user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_charge_id ON transactions(charge_id) WHERE charge_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_transactions_user_created_at ON transactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC);
"""


PRAGMAS = [
    "PRAGMA foreign_keys = ON;",
    "PRAGMA journal_mode = WAL;",
    "PRAGMA busy_timeout = 5000;",
]


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        if self.path.parent:
            os.makedirs(self.path.parent, exist_ok=True)

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        for pragma in PRAGMAS:
            await conn.execute(pragma)
        return conn

    async def init(self) -> None:
        conn = await self._connect()
        try:
            await conn.executescript(CREATE_SQL)
            await conn.commit()
        finally:
            await conn.close()

    async def ensure_user(self, user_id: int, username: Optional[str]) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                INSERT INTO users(user_id, username)
                VALUES(?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=COALESCE(excluded.username, users.username),
                    updated_at=datetime('now')
                """,
                (user_id, username),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def _ensure_user_tx(self, conn: aiosqlite.Connection, user_id: int, username: Optional[str]) -> None:
        await conn.execute(
            """
            INSERT INTO users(user_id, username)
            VALUES(?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=COALESCE(excluded.username, users.username),
                updated_at=datetime('now')
            """,
            (user_id, username),
        )

    async def get_balance(self, user_id: int) -> int:
        conn = await self._connect()
        try:
            cur = await conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            return int(row["balance"]) if row else 0
        finally:
            await conn.close()

    async def _get_balance_tx(self, conn: aiosqlite.Connection, user_id: int) -> int:
        cur = await conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return int(row["balance"]) if row else 0

    async def payment_exists(self, charge_id: str) -> bool:
        conn = await self._connect()
        try:
            cur = await conn.execute("SELECT 1 FROM payments WHERE charge_id=?", (charge_id,))
            return await cur.fetchone() is not None
        finally:
            await conn.close()

    async def add_purchase(self, user_id: int, username: Optional[str], amount: int, charge_id: str) -> bool:
        conn = await self._connect()
        try:
            await conn.execute("BEGIN")
            await self._ensure_user_tx(conn, user_id, username)

            cur = await conn.execute("SELECT id, refunded FROM payments WHERE charge_id=?", (charge_id,))
            if await cur.fetchone():
                await conn.rollback()
                return False

            await conn.execute(
                """
                INSERT INTO payments(user_id, amount, currency, charge_id, refunded)
                VALUES(?, ?, 'XTR', ?, 0)
                """,
                (user_id, amount, charge_id),
            )
            await conn.execute(
                """
                UPDATE users
                SET balance = balance + ?, updated_at=datetime('now')
                WHERE user_id=?
                """,
                (amount, user_id),
            )
            balance_after = await self._get_balance_tx(conn, user_id)
            await self._insert_transaction(
                conn,
                user_id=user_id,
                tx_type="purchase",
                amount=amount,
                charge_id=charge_id,
                description="Покупка Stars через Telegram",
                balance_after=balance_after,
            )
            await conn.commit()
            return True
        finally:
            await conn.close()

    async def transfer(
        self, from_user: int, to_user: int, amount: int, from_username: Optional[str], to_username: Optional[str]
    ) -> int:
        if amount <= 0:
            raise ValueError("amount must be positive")

        conn = await self._connect()
        try:
            await conn.execute("BEGIN")
            await self._ensure_user_tx(conn, from_user, from_username)
            await self._ensure_user_tx(conn, to_user, to_username)

            sender_balance = await self._get_balance_tx(conn, from_user)
            if sender_balance < amount:
                await conn.rollback()
                raise ValueError("insufficient_funds")

            await conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at=datetime('now') WHERE user_id=?",
                (amount, from_user),
            )
            await conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at=datetime('now') WHERE user_id=?",
                (amount, to_user),
            )

            transfer_cur = await conn.execute(
                "INSERT INTO transfers(from_user_id, to_user_id, amount) VALUES(?, ?, ?)",
                (from_user, to_user, amount),
            )
            transfer_id = transfer_cur.lastrowid

            sender_after = await self._get_balance_tx(conn, from_user)
            receiver_after = await self._get_balance_tx(conn, to_user)
            await self._insert_transaction(
                conn,
                user_id=from_user,
                tx_type="gift_out",
                amount=amount,
                related_user_id=to_user,
                description=f"Подарок {amount}⭐ пользователю {to_user}",
                balance_after=sender_after,
            )
            await self._insert_transaction(
                conn,
                user_id=to_user,
                tx_type="gift_in",
                amount=amount,
                related_user_id=from_user,
                description=f"Получен подарок {amount}⭐ от пользователя {from_user}",
                balance_after=receiver_after,
            )
            await conn.commit()
            return transfer_id
        finally:
            await conn.close()

    async def mark_refund(self, user_id: int, charge_id: str, amount: int) -> bool:
        conn = await self._connect()
        try:
            await conn.execute("BEGIN")
            cur = await conn.execute(
                "SELECT id, amount, refunded FROM payments WHERE charge_id=? AND user_id=?",
                (charge_id, user_id),
            )
            row = await cur.fetchone()
            if not row or row["refunded"]:
                await conn.rollback()
                return False

            if int(row["amount"]) != int(amount):
                await conn.rollback()
                return False

            current_balance = await self._get_balance_tx(conn, user_id)
            if current_balance < amount:
                await conn.rollback()
                return False

            await conn.execute("UPDATE payments SET refunded=1 WHERE id=?", (row["id"],))
            await conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at=datetime('now') WHERE user_id=?",
                (amount, user_id),
            )
            balance_after = await self._get_balance_tx(conn, user_id)
            await self._insert_transaction(
                conn,
                user_id=user_id,
                tx_type="refund",
                amount=amount,
                charge_id=charge_id,
                description="Возврат Stars пользователю",
                balance_after=balance_after,
            )
            await conn.commit()
            return True
        finally:
            await conn.close()

    async def _insert_transaction(
        self,
        conn: aiosqlite.Connection,
        user_id: int,
        tx_type: str,
        amount: int,
        related_user_id: Optional[int] = None,
        charge_id: Optional[str] = None,
        description: Optional[str] = None,
        balance_after: Optional[int] = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO transactions(user_id, type, amount, related_user_id, charge_id, description, balance_after)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, tx_type, amount, related_user_id, charge_id, description, balance_after),
        )

    async def get_transactions(self, user_id: int, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        conn = await self._connect()
        try:
            cur = await conn.execute(
                """
                SELECT id, type, amount, related_user_id, charge_id, description, balance_after, created_at
                FROM transactions
                WHERE user_id=?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            )
            rows = await cur.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def count_transactions(self, user_id: int) -> int:
        conn = await self._connect()
        try:
            cur = await conn.execute(
                "SELECT COUNT(*) AS cnt FROM transactions WHERE user_id=?",
                (user_id,),
            )
            row = await cur.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            await conn.close()

    async def top_balances(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = await self._connect()
        try:
            cur = await conn.execute(
                "SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?",
                (limit,),
            )
            rows = await cur.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_payment_for_amount(self, user_id: int, amount: int) -> Optional[Dict[str, Any]]:
        conn = await self._connect()
        try:
            cur = await conn.execute(
                """
                SELECT id, charge_id, refunded, amount
                FROM payments
                WHERE user_id=? AND amount=? AND refunded=0
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, amount),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await conn.close()
