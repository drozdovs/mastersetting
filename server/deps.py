# -*- coding: utf-8 -*-
"""FastAPI-зависимости: авторизация пользователей и агентов."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import Agent, Role, User
from .security import decode_token


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    token = authorization.replace("Bearer ", "").strip()
    payload = decode_token(token) if token else None
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")
    user = db.query(User).filter(User.login == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь неактивен")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора")
    return user


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in (Role.admin, Role.manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
    return user


def get_agent(
    x_agent_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Agent:
    payload = decode_token(x_agent_token) if x_agent_token else None
    if not payload or payload.get("type") != "agent":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный токен агента")
    agent = db.query(Agent).filter(Agent.agent_id == payload.get("sub")).first()
    if not agent:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Агент не зарегистрирован")
    return agent
