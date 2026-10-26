from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.providers.models import CATALOG, COMING_SOON, DEFAULT_ENGINES, available_engines
from app.users.models import User

router = APIRouter(prefix="/engines", tags=["Engines"])


@router.get("")
def list_engines(current_user: User = Depends(get_current_user)):
    """Every AI engine a project can scan, in display order, and whether this deployment can reach it."""
    reachable = {e.key for e in available_engines()}
    return [
        {"key": e.key, "name": e.display_name, "web_search": e.web_search or e.key == "perplexity",
         "available": e.key in reachable, "default": e.key in DEFAULT_ENGINES}
        for e in CATALOG
    ] + [{"key": k, "name": n, "web_search": False, "available": False, "default": False} for k, n in COMING_SOON.items()]
