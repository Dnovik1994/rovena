from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.project import Project
from app.models.source import Source
from app.models.user import User
from app.schemas.source import SourceCreate, SourceResponse, SourceUpdate

router = APIRouter(tags=["sources"])


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SourceResponse]:
    sources = (
        db.query(Source)
        .filter(Source.owner_id == current_user.id)
        .order_by(Source.created_at.desc())
        .all()
    )
    return [SourceResponse.model_validate(source) for source in sources]


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceResponse:
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    source = Source(
        project_id=payload.project_id,
        owner_id=current_user.id,
        name=payload.name,
        link=payload.link,
        type=payload.type,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return SourceResponse.model_validate(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceResponse:
    source = (
        db.query(Source)
        .filter(Source.owner_id == current_user.id, Source.id == source_id)
        .first()
    )
    if not source:
        existing = db.get(Source, source_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    if payload.name is not None:
        source.name = payload.name
    if payload.link is not None:
        source.link = payload.link
    if payload.type is not None:
        source.type = payload.type

    db.commit()
    db.refresh(source)
    return SourceResponse.model_validate(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    source = (
        db.query(Source)
        .filter(Source.owner_id == current_user.id, Source.id == source_id)
        .first()
    )
    if not source:
        existing = db.get(Source, source_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    db.delete(source)
    db.commit()
    return None
