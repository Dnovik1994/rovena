import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.admin_notification_setting import AdminNotificationSetting
from app.models.telegram_account import TelegramAccount
from app.models.warming_bio import WarmingBio
from app.models.warming_channel import WarmingChannel
from app.models.warming_name import WarmingName
from app.models.warming_photo import WarmingPhoto
from app.models.warming_username import WarmingUsername
from app.schemas.admin_warming import (
    NotificationSettingCreate,
    NotificationSettingResponse,
    NotificationSettingUpdate,
    TrustedAccountResponse,
    TrustedAccountToggle,
    WarmingBioCreate,
    WarmingBioResponse,
    WarmingChannelCreate,
    WarmingChannelResponse,
    WarmingNameCreate,
    WarmingNameResponse,
    WarmingPhotoResponse,
    WarmingUsernameCreate,
    WarmingUsernameResponse,
)

router = APIRouter(tags=["admin-warming"])
logger = logging.getLogger(__name__)

WARMING_PHOTOS_DIR = Path("/app/data/warming_photos")
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5 MB


# ── Warming Channels ──


@router.get("/channels", response_model=list[WarmingChannelResponse])
def list_channels(
    is_active: bool | None = Query(default=None),
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[WarmingChannelResponse]:
    query = db.query(WarmingChannel)
    if is_active is not None:
        query = query.filter(WarmingChannel.is_active == is_active)
    items = query.order_by(WarmingChannel.created_at.desc()).all()
    return [WarmingChannelResponse.model_validate(i) for i in items]


@router.post(
    "/channels",
    response_model=WarmingChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_channel(
    payload: WarmingChannelCreate,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> WarmingChannelResponse:
    channel = WarmingChannel(
        username=payload.username,
        channel_type=payload.channel_type,
        language=payload.language,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return WarmingChannelResponse.model_validate(channel)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    channel_id: int,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    channel = db.get(WarmingChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    channel.is_active = False
    db.commit()


# ── Warming Bios ──


@router.get("/bios", response_model=list[WarmingBioResponse])
def list_bios(
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[WarmingBioResponse]:
    items = (
        db.query(WarmingBio)
        .filter(WarmingBio.is_active == True)  # noqa: E712
        .order_by(WarmingBio.created_at.desc())
        .all()
    )
    return [WarmingBioResponse.model_validate(i) for i in items]


@router.post(
    "/bios",
    response_model=WarmingBioResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_bio(
    payload: WarmingBioCreate,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> WarmingBioResponse:
    bio = WarmingBio(text=payload.text)
    db.add(bio)
    db.commit()
    db.refresh(bio)
    return WarmingBioResponse.model_validate(bio)


@router.delete("/bios/{bio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bio(
    bio_id: int,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    bio = db.get(WarmingBio, bio_id)
    if not bio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bio not found")
    bio.is_active = False
    db.commit()


# ── Warming Photos ──


@router.get("/photos", response_model=list[WarmingPhotoResponse])
def list_photos(
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[WarmingPhotoResponse]:
    items = (
        db.query(WarmingPhoto)
        .order_by(WarmingPhoto.created_at.desc())
        .all()
    )
    return [WarmingPhotoResponse.model_validate(i) for i in items]


@router.post(
    "/photos",
    response_model=WarmingPhotoResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_photo(
    file: UploadFile = File(...),
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> WarmingPhotoResponse:
    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Accepted: jpg, png, webp",
        )

    contents = file.file.read()
    if len(contents) > MAX_PHOTO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Max 5MB",
        )

    WARMING_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4()}_{file.filename}"
    dest = WARMING_PHOTOS_DIR / unique_name

    with open(dest, "wb") as f:
        f.write(contents)

    photo = WarmingPhoto(
        filename=file.filename or unique_name,
        file_path=str(dest),
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return WarmingPhotoResponse.model_validate(photo)


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(
    photo_id: int,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    photo = db.get(WarmingPhoto, photo_id)
    if not photo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    photo.is_active = False
    db.commit()

    # Remove file from disk (best-effort)
    try:
        file_path = Path(photo.file_path)
        if file_path.exists():
            file_path.unlink()
    except OSError:
        logger.warning("Failed to delete photo file: %s", photo.file_path)


# ── Warming Usernames ──


@router.get("/usernames", response_model=list[WarmingUsernameResponse])
def list_usernames(
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[WarmingUsernameResponse]:
    items = (
        db.query(WarmingUsername)
        .filter(WarmingUsername.is_active == True)  # noqa: E712
        .order_by(WarmingUsername.created_at.desc())
        .all()
    )
    return [WarmingUsernameResponse.model_validate(i) for i in items]


@router.post(
    "/usernames",
    response_model=WarmingUsernameResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_username(
    payload: WarmingUsernameCreate,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> WarmingUsernameResponse:
    uname = WarmingUsername(template=payload.template)
    db.add(uname)
    db.commit()
    db.refresh(uname)
    return WarmingUsernameResponse.model_validate(uname)


@router.delete("/usernames/{username_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_username(
    username_id: int,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    uname = db.get(WarmingUsername, username_id)
    if not uname:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Username not found")
    uname.is_active = False
    db.commit()


# ── Warming Names ──


@router.get("/names", response_model=list[WarmingNameResponse])
def list_names(
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[WarmingNameResponse]:
    items = (
        db.query(WarmingName)
        .filter(WarmingName.is_active == True)  # noqa: E712
        .order_by(WarmingName.created_at.desc())
        .all()
    )
    return [WarmingNameResponse.model_validate(i) for i in items]


@router.post(
    "/names",
    response_model=WarmingNameResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_name(
    payload: WarmingNameCreate,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> WarmingNameResponse:
    name = WarmingName(
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(name)
    db.commit()
    db.refresh(name)
    return WarmingNameResponse.model_validate(name)


@router.delete("/names/{name_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_name(
    name_id: int,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    name = db.get(WarmingName, name_id)
    if not name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Name not found")
    name.is_active = False
    db.commit()


# ── Trusted Accounts ──


@router.patch("/accounts/{account_id}/trusted", response_model=TrustedAccountResponse)
def toggle_trusted(
    account_id: int,
    payload: TrustedAccountToggle,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TrustedAccountResponse:
    account = db.get(TelegramAccount, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    account.is_trusted = payload.is_trusted
    db.commit()
    db.refresh(account)
    return TrustedAccountResponse.model_validate(account)


@router.get("/accounts/trusted", response_model=list[TrustedAccountResponse])
def list_trusted_accounts(
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[TrustedAccountResponse]:
    items = (
        db.query(TelegramAccount)
        .filter(TelegramAccount.is_trusted == True)  # noqa: E712
        .order_by(TelegramAccount.created_at.desc())
        .all()
    )
    return [TrustedAccountResponse.model_validate(i) for i in items]


# ── Notification Settings ──


@router.get("/notifications", response_model=list[NotificationSettingResponse])
def list_notifications(
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[NotificationSettingResponse]:
    items = (
        db.query(AdminNotificationSetting)
        .order_by(AdminNotificationSetting.created_at.desc())
        .all()
    )
    return [NotificationSettingResponse.model_validate(i) for i in items]


@router.post(
    "/notifications",
    response_model=NotificationSettingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_notification(
    payload: NotificationSettingCreate,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> NotificationSettingResponse:
    setting = AdminNotificationSetting(
        chat_id=payload.chat_id,
        notify_account_banned=payload.notify_account_banned,
        notify_flood_wait=payload.notify_flood_wait,
        notify_warming_failed=payload.notify_warming_failed,
        notify_system_health=payload.notify_system_health,
        notify_flood_rate_threshold=payload.notify_flood_rate_threshold,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return NotificationSettingResponse.model_validate(setting)


@router.patch("/notifications/{notification_id}", response_model=NotificationSettingResponse)
def update_notification(
    notification_id: int,
    payload: NotificationSettingUpdate,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> NotificationSettingResponse:
    setting = db.get(AdminNotificationSetting, notification_id)
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification setting not found",
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(setting, field, value)
    db.commit()
    db.refresh(setting)
    return NotificationSettingResponse.model_validate(setting)


@router.delete("/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    _admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    setting = db.get(AdminNotificationSetting, notification_id)
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification setting not found",
        )
    db.delete(setting)
    db.commit()
