# -*- coding: utf-8 -*-
"""FastAPI-приложение MasterSetting Server."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import SessionLocal, engine
from .models import Base, Role, User
from .routers import agents, auth_users, catalog, export, releases
from .security import hash_password
from .settings import settings


def init_db() -> None:
    """Создать таблицы и первого администратора при пустой БД."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(
                login=settings.admin_login,
                full_name="Администратор",
                password_hash=hash_password(settings.admin_password),
                role=Role.admin,
            ))
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    os.makedirs(settings.releases_dir, exist_ok=True)
    yield


app = FastAPI(title="MasterSetting Server", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API
app.include_router(auth_users.router)
app.include_router(auth_users.users_router)
app.include_router(catalog.router)
app.include_router(agents.router)
app.include_router(agents.admin_router)
app.include_router(releases.router)
app.include_router(export.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}


# Раздача собранной веб-админки (если есть).
# ВАЖНО: StaticFiles не умеет SPA-fallback, поэтому deep-link маршруты
# React Router (/releases, /agents, …) отдавали бы 404. Монтируем assets,
# а все прочие не-API пути возвращают index.html.
_web_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_web_dist):
    _assets = os.path.join(_web_dist, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # Неизвестные API-пути — честный 404, а не index.html
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = os.path.join(_web_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_web_dist, "index.html"))
