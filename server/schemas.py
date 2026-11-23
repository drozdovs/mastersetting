# -*- coding: utf-8 -*-
"""Pydantic-схемы API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


# --- Auth ---
class LoginIn(BaseModel):
    login: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = ""


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login: str
    full_name: str
    role: str
    is_active: bool
    group_id: int | None = None


class UserCreate(BaseModel):
    login: str
    password: str
    full_name: str = ""
    role: str = "viewer"
    group_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    group_id: int | None = None
    password: str | None = None


# --- Groups ---
class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str


class GroupCreate(BaseModel):
    name: str
    description: str = ""


# --- Cameras ---
class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    model: str
    notes: str
    is_active: bool


class CameraCreate(BaseModel):
    name: str
    model: str = ""
    notes: str = ""


class CameraUpdate(BaseModel):
    model: str | None = None
    notes: str | None = None
    is_active: bool | None = None


# --- Events / stats ---
class EventIn(BaseModel):
    kind: str
    status: str
    operator: str = ""
    camera: str = ""
    settings_name: str = ""
    drive: str = ""
    message: str = ""
    bytes: int = 0
    files: int = 0
    created_at: dt.datetime | None = None


class EventSyncIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    operator: str
    camera: str
    settings_name: str
    bytes: int
    files: int
    created_at: dt.datetime


# --- Agent ---
class AgentRegisterIn(BaseModel):
    agent_id: str
    hostname: str = ""
    os_info: str = ""
    version: str = ""


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    hostname: str
    os_info: str
    version: str
    last_seen: dt.datetime


class HeartbeatIn(BaseModel):
    agent_id: str
    version: str = ""


class SettingIn(BaseModel):
    operator: str
    camera: str
    settings_name: str
    path_on_agent: str = ""
    size_bytes: int = 0
    manifest: str = ""


# --- Release / update ---
class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: str
    notes: str
    filename: str
    sha256: str
    mandatory: bool
    is_published: bool


class ReleaseCreate(BaseModel):
    version: str
    notes: str = ""
    filename: str = ""
    mandatory: bool = False
