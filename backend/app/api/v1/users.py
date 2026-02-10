from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_current_user_id
from app.core.cache import delete
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserOnboardingUpdate, UserResponse

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserResponse)
async def read_me(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/users/me/onboarding", response_model=UserResponse)
async def complete_onboarding(
    payload: UserOnboardingUpdate,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, current_user_id)
    if not user:
        from app.core.errors import unauthorized

        raise unauthorized("User not found")

    user.onboarding_completed = payload.onboarding_completed
    db.commit()
    db.refresh(user)
    await delete(f"user:{user.id}")
    return UserResponse.model_validate(user)
