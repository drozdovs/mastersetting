# -*- coding: utf-8 -*-
"""Агенты: регистрация, heartbeat, синхронизация настроек и событий."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_agent, get_current_user, require_admin, require_manager
from ..models import Agent, Camera, Event, Setting, User, utcnow
from ..schemas import (
    AgentOut, AgentRegisterIn, EventOut, EventSyncIn, HeartbeatIn, SettingIn,
)
from ..security import create_agent_token

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/config")
def agent_config(db: Session = Depends(get_db), agent: Agent = Depends(get_agent)):
    """Конфиг для агента: список активных камер и операторов.

    Агент кэширует ответ локально и продолжает работать офлайн; при обрыве
    связи использует последнюю успешную версию.
    """
    cameras = [c.name for c in
               db.query(Camera).filter(Camera.is_active.is_(True))
               .order_by(Camera.name).all()]
    operators = [o for (o,) in
                 db.query(Event.operator)
                 .filter(Event.operator != "")
                 .distinct().order_by(Event.operator).all()]
    return {
        "cameras": cameras,
        "operators": operators,
        "server_time": utcnow().isoformat(),
    }


@router.post("/register")
def register_agent(data: AgentRegisterIn, db: Session = Depends(get_db)):
    """Регистрация агента. Возвращает его постоянный токен."""
    agent = db.query(Agent).filter(Agent.agent_id == data.agent_id).first()
    if not agent:
        agent = Agent(agent_id=data.agent_id)
        db.add(agent)
    agent.hostname = data.hostname
    agent.os_info = data.os_info
    agent.version = data.version
    agent.last_seen = utcnow()
    db.commit()
    token = create_agent_token(data.agent_id)
    return {"agent_id": data.agent_id, "token": token}


@router.post("/heartbeat")
def heartbeat(data: HeartbeatIn, db: Session = Depends(get_db),
              agent: Agent = Depends(get_agent)):
    agent.version = data.version or agent.version
    agent.last_seen = utcnow()
    db.commit()
    return {"ok": True, "server_time": utcnow().isoformat()}


@router.post("/settings")
def push_setting(data: SettingIn, db: Session = Depends(get_db),
                 agent: Agent = Depends(get_agent)):
    """Агент сообщает о сохранённом наборе настроек (метаданные)."""
    setting = (db.query(Setting)
               .filter(Setting.operator == data.operator,
                       Setting.camera == data.camera,
                       Setting.settings_name == data.settings_name,
                       Setting.agent_id == agent.agent_id)
               .first())
    if not setting:
        setting = Setting(operator=data.operator, camera=data.camera,
                          settings_name=data.settings_name,
                          agent_id=agent.agent_id)
        db.add(setting)
    setting.path_on_agent = data.path_on_agent
    setting.size_bytes = data.size_bytes
    setting.manifest = data.manifest
    agent.last_seen = utcnow()
    db.commit()
    return {"ok": True, "id": setting.id}


@router.post("/events")
def sync_events(data: EventSyncIn, db: Session = Depends(get_db),
                agent: Agent = Depends(get_agent)):
    """Пакетная загрузка событий (журнал операций)."""
    added = 0
    for ev in data.events:
        db.add(Event(
            kind=ev.kind, status=ev.status, operator=ev.operator,
            camera=ev.camera, settings_name=ev.settings_name, drive=ev.drive,
            message=ev.message, bytes=ev.bytes, files=ev.files,
            agent_id=agent.agent_id,
            created_at=ev.created_at or utcnow(),
        ))
        added += 1
    agent.last_seen = utcnow()
    db.commit()
    return {"ok": True, "added": added}


# ---------------------------------------------------------------------------
# Просмотр (для админки)
# ---------------------------------------------------------------------------

admin_router = APIRouter(prefix="/api", tags=["admin"])


@admin_router.get("/agents", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Agent).order_by(Agent.last_seen.desc()).all()


@admin_router.patch("/agents/{agent_pk}")
def update_agent(agent_pk: int, payload: dict, db: Session = Depends(get_db),
                 _: User = Depends(require_manager)):
    """Удалённое управление агентом: название, группа."""
    agent = db.get(Agent, agent_pk)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Агент не найден")
    if "hostname" in payload and payload["hostname"]:
        agent.hostname = payload["hostname"]
    if "group_id" in payload:
        agent.group_id = payload["group_id"] or None
    db.commit()
    db.refresh(agent)
    return {"ok": True, "id": agent.id}


@admin_router.delete("/agents/{agent_pk}")
def delete_agent(agent_pk: int, db: Session = Depends(get_db),
                 _: User = Depends(require_admin)):
    agent = db.get(Agent, agent_pk)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Агент не найден")
    db.delete(agent)
    db.commit()
    return {"ok": True}


@admin_router.get("/agents/{agent_pk}/settings")
def agent_settings(agent_pk: int, db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    """Наборы настроек, зарегистрированные конкретным агентом."""
    agent = db.get(Agent, agent_pk)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Агент не найден")
    rows = (db.query(Setting)
            .filter(Setting.agent_id == agent.agent_id)
            .order_by(Setting.created_at.desc()).all())
    return [{
        "id": s.id, "operator": s.operator, "camera": s.camera,
        "settings_name": s.settings_name, "size_bytes": s.size_bytes,
        "created_at": s.created_at.isoformat(),
    } for s in rows]


@admin_router.get("/events", response_model=list[EventOut])
def list_events(limit: int = 100, db: Session = Depends(get_db),
                _: User = Depends(get_current_user)):
    return (db.query(Event).order_by(Event.created_at.desc())
            .limit(min(limit, 1000)).all())


@admin_router.get("/stats")
def get_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    total = db.query(func.count(Event.id)).scalar() or 0
    saves = db.query(func.count(Event.id)).filter(
        Event.kind == "save", Event.status == "ok").scalar() or 0
    loads = db.query(func.count(Event.id)).filter(
        Event.kind == "load", Event.status == "ok").scalar() or 0
    errors = db.query(func.count(Event.id)).filter(Event.status == "error").scalar() or 0
    agents = db.query(func.count(Agent.id)).scalar() or 0
    settings_count = db.query(func.count(Setting.id)).scalar() or 0

    online_threshold = utcnow() - dt.timedelta(minutes=2)
    online = db.query(func.count(Agent.id)).filter(
        Agent.last_seen >= online_threshold).scalar() or 0

    top_ops = (db.query(Event.operator, func.count(Event.id).label("c"))
               .filter(Event.status == "ok", Event.operator != "")
               .group_by(Event.operator).order_by(func.count(Event.id).desc())
               .limit(10).all())

    return {
        "events_total": total,
        "saves_ok": saves,
        "loads_ok": loads,
        "errors": errors,
        "agents_total": agents,
        "agents_online": online,
        "settings_count": settings_count,
        "top_operators": [{"operator": op, "count": c} for op, c in top_ops],
    }
