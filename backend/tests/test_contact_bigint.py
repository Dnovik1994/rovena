"""Verify that contacts.telegram_id supports values exceeding 2^31."""

from app.core.database import SessionLocal
from app.models.contact import Contact
from app.models.project import Project
from app.models.user import User


LARGE_TELEGRAM_ID = 6_887_867_394  # > 2^31 (2_147_483_648)


def test_contact_telegram_id_bigint(db_session):
    """Contact.telegram_id must accept values larger than 32-bit INT max."""
    user = User(telegram_id=LARGE_TELEGRAM_ID + 1, username="biguser", first_name="Big")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    project = Project(owner_id=user.id, name="BigID Project", description=None)
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    contact = Contact(
        project_id=project.id,
        owner_id=user.id,
        source_id=None,
        telegram_id=LARGE_TELEGRAM_ID,
        username="bigcontact",
        first_name="Contact",
    )
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)

    assert contact.telegram_id == LARGE_TELEGRAM_ID

    # Re-read from DB to confirm persistence
    fetched = db_session.get(Contact, contact.id)
    assert fetched is not None
    assert fetched.telegram_id == LARGE_TELEGRAM_ID
