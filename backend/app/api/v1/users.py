from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.cache import delete
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserOnboardingUpdate, UserResponse

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/users/me/onboarding", response_model=UserResponse)
async def complete_onboarding(
    payload: UserOnboardingUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    current_user.onboarding_completed = payload.onboarding_completed
    db.commit()
    db.refresh(current_user)
    await delete(f"user:{current_user.id}")
    return UserResponse.model_validate(current_user)
