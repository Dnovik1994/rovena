from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.project import Project
from app.models.target import Target
from app.models.user import User
from app.schemas.target import TargetCreate, TargetResponse, TargetUpdate

router = APIRouter(tags=["targets"])


@router.get("/targets", response_model=list[TargetResponse])
async def list_targets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TargetResponse]:
    targets = (
        db.query(Target)
        .filter(Target.owner_id == current_user.id)
        .order_by(Target.created_at.desc())
        .all()
    )
    return [TargetResponse.model_validate(target) for target in targets]


@router.post("/targets", response_model=TargetResponse, status_code=status.HTTP_201_CREATED)
async def create_target(
    payload: TargetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TargetResponse:
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    target = Target(
        project_id=payload.project_id,
        owner_id=current_user.id,
        name=payload.name,
        link=payload.link,
        type=payload.type,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return TargetResponse.model_validate(target)


@router.patch("/targets/{target_id}", response_model=TargetResponse)
async def update_target(
    target_id: int,
    payload: TargetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TargetResponse:
    target = (
        db.query(Target)
        .filter(Target.owner_id == current_user.id, Target.id == target_id)
        .first()
    )
    if not target:
        existing = db.get(Target, target_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")

    if payload.name is not None:
        target.name = payload.name
    if payload.link is not None:
        target.link = payload.link
    if payload.type is not None:
        target.type = payload.type

    db.commit()
    db.refresh(target)
    return TargetResponse.model_validate(target)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    target = (
        db.query(Target)
        .filter(Target.owner_id == current_user.id, Target.id == target_id)
        .first()
    )
    if not target:
        existing = db.get(Target, target_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")

    db.delete(target)
    db.commit()
    return None
