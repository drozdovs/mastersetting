# -*- coding: utf-8 -*-
"""Релизы агента (публикация обновлений и выдача агентам)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_agent, get_current_user, require_admin
from ..models import Release, User
from ..schemas import ReleaseCreate, ReleaseOut
from ..settings import settings

router = APIRouter(prefix="/api", tags=["releases"])


@router.get("/releases", response_model=list[ReleaseOut])
def list_releases(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Release).order_by(Release.created_at.desc()).all()


@router.post("/releases", response_model=ReleaseOut)
def create_release(data: ReleaseCreate, db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    if db.query(Release).filter(Release.version == data.version).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Версия уже существует")
    rel = Release(version=data.version, notes=data.notes,
                  filename=data.filename, mandatory=data.mandatory)
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


@router.post("/releases/{release_id}/upload")
async def upload_release_file(release_id: int, file: UploadFile = File(...),
                              db: Session = Depends(get_db),
                              _: User = Depends(require_admin)):
    rel = db.get(Release, release_id)
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Релиз не найден")
    os.makedirs(settings.releases_dir, exist_ok=True)
    dest = os.path.join(settings.releases_dir, file.filename)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)
    import hashlib
    rel.filename = file.filename
    rel.sha256 = hashlib.sha256(content).hexdigest()
    db.commit()
    return {"ok": True, "filename": rel.filename, "sha256": rel.sha256}


@router.post("/releases/{release_id}/publish", response_model=ReleaseOut)
def publish_release(release_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_admin)):
    rel = db.get(Release, release_id)
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Релиз не найден")
    rel.is_published = True
    db.commit()
    db.refresh(rel)
    return rel


# --- Для агента ---

@router.get("/agent/update")
def check_update(current: str = "", db: Session = Depends(get_db),
                 agent=Depends(get_agent)):
    """Последний опубликованный релиз, если он новее ``current``."""
    rel = (db.query(Release).filter(Release.is_published.is_(True))
           .order_by(Release.created_at.desc()).first())
    if not rel:
        return {"update": False}
    if rel.version == current:
        return {"update": False, "version": rel.version}
    return {
        "update": True,
        "version": rel.version,
        "mandatory": rel.mandatory,
        "notes": rel.notes,
        "sha256": rel.sha256,
        "url": f"/api/agent/download/{rel.version}",
    }


@router.get("/agent/download/{version}")
def download_release(version: str, db: Session = Depends(get_db),
                     agent=Depends(get_agent)):
    rel = db.query(Release).filter(Release.version == version).first()
    if not rel or not rel.filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл релиза не найден")
    path = os.path.join(settings.releases_dir, rel.filename)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл недоступен")
    return FileResponse(path, filename=rel.filename)
