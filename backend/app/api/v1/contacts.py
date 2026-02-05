from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.models.contact import Contact
from app.models.project import Project
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactResponse, ContactUpdate

router = APIRouter(tags=["contacts"])


@router.get("/contacts", response_model=list[ContactResponse])
async def list_contacts(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ContactResponse]:
    contacts = (
        db.query(Contact)
        .filter(Contact.owner_id == current_user.id)
        .order_by(Contact.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [ContactResponse.model_validate(contact) for contact in contacts]


@router.post("/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ContactResponse:
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    contact = Contact(
        project_id=payload.project_id,
        owner_id=current_user.id,
        source_id=payload.source_id,
        telegram_id=payload.telegram_id,
        username=payload.username,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        tags=payload.tags,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.patch("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ContactResponse:
    contact = (
        db.query(Contact)
        .filter(Contact.owner_id == current_user.id, Contact.id == contact_id)
        .first()
    )
    if not contact:
        existing = db.get(Contact, contact_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    if payload.first_name is not None:
        contact.first_name = payload.first_name
    if payload.last_name is not None:
        contact.last_name = payload.last_name
    if payload.username is not None:
        contact.username = payload.username
    if payload.phone is not None:
        contact.phone = payload.phone
    if payload.tags is not None:
        contact.tags = payload.tags

    db.commit()
    db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> None:
    contact = (
        db.query(Contact)
        .filter(Contact.owner_id == current_user.id, Contact.id == contact_id)
        .first()
    )
    if not contact:
        existing = db.get(Contact, contact_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    db.delete(contact)
    db.commit()
    return None
