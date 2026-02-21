from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_warming,
    analytics,
    api_apps,
    auth,
    campaigns,
    contacts,
    health,
    invite_campaigns,
    projects,
    proxies,
    sources,
    targets,
    tg_accounts,
    users,
)

router = APIRouter()

router.include_router(auth.router)
router.include_router(users.router)
router.include_router(projects.router)
router.include_router(sources.router)
router.include_router(targets.router)
router.include_router(contacts.router)
router.include_router(campaigns.router)
router.include_router(tg_accounts.router)
router.include_router(proxies.router)
router.include_router(api_apps.router)
router.include_router(admin.router, prefix="/admin")
router.include_router(admin_warming.router, prefix="/admin/warming")
router.include_router(invite_campaigns.router)
router.include_router(analytics.router)
router.include_router(health.router)
