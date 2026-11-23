# -*- coding: utf-8 -*-
"""Группы и камеры."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin, require_manager
from ..models import Camera, Group, User
from ..schemas import CameraCreate, CameraOut, CameraUpdate, GroupCreate, GroupOut

router = APIRouter(prefix="/api", tags=["catalog"])


# ---------------------------------------------------------------------------
# Группы
# ---------------------------------------------------------------------------

@router.get("/groups", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Group).order_by(Group.name).all()


@router.post("/groups", response_model=GroupOut)
def create_group(data: GroupCreate, db: Session = Depends(get_db),
                 _: User = Depends(require_admin)):
    if db.query(Group).filter(Group.name == data.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Группа уже существует")
    group = Group(name=data.name, description=data.description)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db),
                 _: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    db.delete(group)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Камеры
# ---------------------------------------------------------------------------

@router.get("/cameras", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Camera).order_by(Camera.name).all()


@router.post("/cameras", response_model=CameraOut)
def create_camera(data: CameraCreate, db: Session = Depends(get_db),
                  _: User = Depends(require_manager)):
    if db.query(Camera).filter(Camera.name == data.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Камера уже существует")
    cam = Camera(name=data.name, model=data.model, notes=data.notes)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


@router.patch("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, data: CameraUpdate, db: Session = Depends(get_db),
                  _: User = Depends(require_manager)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Камера не найдена")
    if data.model is not None:
        cam.model = data.model
    if data.notes is not None:
        cam.notes = data.notes
    if data.is_active is not None:
        cam.is_active = data.is_active
    db.commit()
    db.refresh(cam)
    return cam


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db),
                  _: User = Depends(require_manager)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Камера не найдена")
    db.delete(cam)
    db.commit()
    return {"ok": True}
