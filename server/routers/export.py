# -*- coding: utf-8 -*-
"""Экспорт статистики (CSV / Excel-совместимый) и отчёты."""

from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Event, User

router = APIRouter(prefix="/api/export", tags=["export"])


def _rows(db: Session) -> list[list]:
    events = db.query(Event).order_by(Event.created_at.desc()).limit(5000).all()
    out = []
    for e in events:
        out.append([
            e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
            "Сохранение" if e.kind == "save" else "Загрузка",
            e.status,
            e.operator, e.camera, e.settings_name,
            e.files, e.bytes, e.agent_id, e.message,
        ])
    return out


HEADER = ["Дата", "Тип", "Статус", "Оператор", "Камера",
          "Настройки", "Файлов", "Байт", "Агент", "Сообщение"]


@router.get("/events.csv")
def export_events_csv(db: Session = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """CSV с BOM (открывается в Excel без «кракозябр»)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(HEADER)
    writer.writerows(_rows(db))
    data = "\ufeff" + buf.getvalue()  # BOM для Excel
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="events_{stamp}.csv"'},
    )


@router.get("/events.xls")
def export_events_xls(db: Session = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """Excel-совместимый экспорт (HTML-таблица с .xls)."""
    rows = _rows(db)
    html = ["<html><head><meta charset='utf-8'></head><body><table border='1'>"]
    html.append("<tr>" + "".join(f"<th>{h}</th>" for h in HEADER) + "</tr>")
    for r in rows:
        html.append("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    html.append("</table></body></html>")
    data = "".join(html)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": f'attachment; filename="events_{stamp}.xls"'},
    )
