from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.audit import AuditLogFilters, AuditLogListResponse, AuditLogRead, AuditPurgeResponse

router = APIRouter(prefix="/audit", tags=["audit"])


def _require_audit_role(user: User) -> None:
    if user.role not in {UserRole.owner, UserRole.coordinator}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _as_datetime(value: datetime | date | None, *, end_of_day: bool) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    base = datetime.combine(value, time.max if end_of_day else time.min)
    return base.replace(tzinfo=UTC)


def _extract_overall_results(screen_results: dict | None) -> dict[str, str]:
    if not isinstance(screen_results, dict):
        return {}
    overall: dict[str, str] = {}
    for trial_id, payload in screen_results.items():
        if isinstance(payload, dict):
            value = payload.get("overall")
            if isinstance(value, str):
                overall[str(trial_id)] = value
    return overall


def _to_read(row: AuditLog, user_email: str | None) -> AuditLogRead:
    return AuditLogRead(
        id=row.id,
        user_id=row.user_id,
        user_email=user_email,
        timestamp=row.timestamp,
        indication=row.indication,
        criteria_version_hash=row.criteria_version_hash,
        engine_version=row.engine_version,
        screen_results=row.screen_results or {},
        exported_at=row.exported_at,
    )


def _with_pagination(
    rows: list[tuple[AuditLog, str | None]],
    limit: int | None,
    offset: int | None,
) -> list[tuple[AuditLog, str | None]]:
    if limit is None and offset is None:
        return rows
    start = offset or 0
    if limit is None:
        return rows[start:]
    return rows[start : start + limit]


async def _fetch_rows(
    db: AsyncSession,
    user: User,
    filters: AuditLogFilters,
) -> list[tuple[AuditLog, str | None]]:
    from_dt = _as_datetime(filters.from_date, end_of_day=False)
    to_dt = _as_datetime(filters.to_date, end_of_day=True)

    query = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.timestamp.desc())
    )
    if user.role == UserRole.coordinator:
        query = query.where(AuditLog.user_id == user.id)
    if filters.user_id:
        query = query.where(AuditLog.user_id == filters.user_id)
    if filters.indication:
        query = query.where(AuditLog.indication == filters.indication)
    if from_dt:
        query = query.where(AuditLog.timestamp >= from_dt)
    if to_dt:
        query = query.where(AuditLog.timestamp <= to_dt)

    result = await db.execute(query)
    rows = [(audit_row, email) for audit_row, email in result.all()]

    if filters.trial_id:
        trial_key = str(filters.trial_id)
        rows = [(audit_row, email) for audit_row, email in rows if trial_key in (audit_row.screen_results or {})]

    return rows


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_id: UUID | None = Query(default=None),
    indication: str | None = Query(default=None),
    from_date: datetime | date | None = Query(default=None),
    to_date: datetime | date | None = Query(default=None),
    trial_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    _require_audit_role(user)

    filters = AuditLogFilters(
        user_id=user_id,
        indication=indication,
        from_date=from_date,
        to_date=to_date,
        trial_id=trial_id,
    )
    rows = await _fetch_rows(db, user, filters)
    total = len(rows)
    paged = _with_pagination(rows, limit=limit, offset=offset)

    return AuditLogListResponse(
        items=[_to_read(audit_row, email) for audit_row, email in paged],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{audit_id}", response_model=AuditLogRead)
async def get_audit_log(
    audit_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogRead:
    _require_audit_role(user)

    result = await db.execute(
        select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).where(AuditLog.id == audit_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit record not found")

    audit_row, email = row
    if user.role == UserRole.coordinator and audit_row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return _to_read(audit_row, email)


@router.post("/export")
async def export_audit_logs(
    payload: AuditLogFilters,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    if user.role != UserRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    rows = await _fetch_rows(db, user, payload)
    rows = _with_pagination(rows, limit=payload.limit, offset=payload.offset)

    now = datetime.now(UTC)
    for audit_row, _ in rows:
        audit_row.exported_at = now
    await db.commit()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp", "user_email", "indication", "engine_version", "overall_results", "exported_at"])
    for audit_row, email in rows:
        writer.writerow(
            [
                str(audit_row.id),
                audit_row.timestamp.isoformat(),
                email or "",
                audit_row.indication,
                audit_row.engine_version,
                json.dumps(_extract_overall_results(audit_row.screen_results), sort_keys=True),
                audit_row.exported_at.isoformat() if audit_row.exported_at else "",
            ]
        )

    filename = f"audit_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("", response_model=AuditPurgeResponse)
async def purge_audit_logs(
    confirm: bool = Query(default=False),
    user_id: UUID | None = Query(default=None),
    indication: str | None = Query(default=None),
    from_date: datetime | date | None = Query(default=None),
    to_date: datetime | date | None = Query(default=None),
    trial_id: UUID | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditPurgeResponse:
    if user.role != UserRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if not confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm=true is required")

    filters = AuditLogFilters(
        user_id=user_id,
        indication=indication,
        from_date=from_date,
        to_date=to_date,
        trial_id=trial_id,
        limit=limit,
        offset=offset,
    )
    rows = await _fetch_rows(db, user, filters)
    rows = _with_pagination(rows, limit=limit, offset=offset)

    now = datetime.now(UTC)
    for audit_row, _ in rows:
        audit_row.exported_at = now
    await db.flush()

    for audit_row, _ in rows:
        await db.delete(audit_row)
    await db.commit()

    return AuditPurgeResponse(deleted=len(rows))
