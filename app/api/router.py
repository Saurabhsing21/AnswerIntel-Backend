from fastapi import APIRouter

from app.auth.router import router as auth_router
from app.projects.router import router as projects_router
from app.competitors.router import router as competitors_router
from app.scans.router import router as scans_router


router = APIRouter(prefix="/api/v1")

router.include_router(projects_router)
router.include_router(auth_router)
router.include_router(competitors_router)
router.include_router(scans_router)