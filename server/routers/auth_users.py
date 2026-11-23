# -*- coding: utf-8 -*-
"""Аутентификация и пользователи."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import Role, User
from ..schemas import LoginIn, TokenOut, UserCreate, UserOut, UserUpdate
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.login == data.login).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена")
    token = create_access_token(user.login, user.role.value)
    return TokenOut(access_token=token, role=user.role.value)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id, login=user.login, full_name=user.full_name,
        role=user.role.value, is_active=user.is_active, group_id=user.group_id,
    )


users_router = APIRouter(prefix="/api/users", tags=["users"])


@users_router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.query(User).order_by(User.id).all()
    return [
        UserOut(id=u.id, login=u.login, full_name=u.full_name, role=u.role.value,
                is_active=u.is_active, group_id=u.group_id)
        for u in users
    ]


@users_router.post("", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    if db.query(User).filter(User.login == data.login).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Логин занят")
    try:
        role = Role(data.role)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверная роль")
    user = User(
        login=data.login, full_name=data.full_name,
        password_hash=hash_password(data.password), role=role,
        group_id=data.group_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, login=user.login, full_name=user.full_name,
                   role=user.role.value, is_active=user.is_active,
                   group_id=user.group_id)


@users_router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.role is not None:
        try:
            user.role = Role(data.role)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверная роль")
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.group_id is not None:
        user.group_id = data.group_id or None
    if data.password:
        user.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, login=user.login, full_name=user.full_name,
                   role=user.role.value, is_active=user.is_active,
                   group_id=user.group_id)


@users_router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    db.delete(user)
    db.commit()
    return {"ok": True}
