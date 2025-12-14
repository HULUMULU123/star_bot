from typing import Any, Dict, List, Optional

from aiogram import Bot
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from config.settings import Settings
from db.database import Database


def create_api_app(settings: Settings, db: Database, bot: Bot) -> FastAPI:
    app = FastAPI(title="Stars Internal API", version="1.0.0")

    async def require_token(authorization: Optional[str] = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != settings.api_token:
            raise HTTPException(status_code=403, detail="Invalid token")

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok"}

    @app.get("/balance/{user_id}")
    async def get_balance(
        user_id: int,
        _=Depends(require_token),
    ) -> Dict[str, Any]:
        balance = await db.get_balance(user_id)
        return {"user_id": user_id, "balance": balance}

    @app.get("/transactions/{user_id}")
    async def get_transactions(
        user_id: int,
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0),
        _=Depends(require_token),
    ) -> Dict[str, Any]:
        items = await db.get_transactions(user_id, limit=limit, offset=offset)
        return {"user_id": user_id, "items": items}

    @app.get("/top")
    async def get_top(
        limit: int = Query(default=10, ge=1, le=50),
        _=Depends(require_token),
    ) -> Dict[str, List[Dict[str, Any]]]:
        items = await db.top_balances(limit=limit)
        return {"items": items}

    @app.get("/telegram/stars/bot-balance")
    async def bot_balance(_=Depends(require_token)) -> Dict[str, Any]:
        try:
            result = await bot.request("getMyStarBalance", {})
        except Exception as exc:  # pragma: no cover - network errors
            raise HTTPException(status_code=502, detail=f"Telegram error: {exc}") from exc
        return result

    return app
