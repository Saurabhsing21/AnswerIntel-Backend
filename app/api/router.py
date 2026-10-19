from fastapi import APIRouter, Depends

from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.common.ratelimit import limit_api
from app.competitors.router import router as competitors_router
from app.experiments.router import router as experiments_router
from app.metrics.router import router as analytics_router
from app.opportunities.router import router as opportunities_router
from app.projects.router import router as projects_router
from app.reports.router import public_router as shared_reports_router
from app.reports.router import router as reports_router
from app.prompts.router import router as prompts_router
from app.scans.router import router as scans_router
from app.waitlist.router import router as waitlist_router
from app.workspaces.router import router as workspaces_router
from app.schedules.router import router as schedules_router

router = APIRouter(prefix="/api/v1", dependencies=[Depends(limit_api)])

router.include_router(auth_router)
router.include_router(projects_router)
router.include_router(competitors_router)
router.include_router(prompts_router)
router.include_router(scans_router)
router.include_router(analytics_router)
router.include_router(opportunities_router)
router.include_router(experiments_router)
router.include_router(schedules_router)
router.include_router(waitlist_router)
router.include_router(workspaces_router)
router.include_router(billing_router)
router.include_router(reports_router)
router.include_router(shared_reports_router)
