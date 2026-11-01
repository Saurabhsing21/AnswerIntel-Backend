from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_active, require_pro
from app.billing.service import active_prompts
from app.common.config import settings
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.costs.service import check_budget
from app.prompts.models import Prompt
from app.prompts.schemas import PromptCreate, PromptsAccept, PromptSuggest, PromptUpdate
from app.prompts.service import PromptDiscoveryService, pool_full_details, pool_full_message
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/prompts", tags=["Prompts"])


def serialize(p: Prompt) -> dict:
    return {
        "id": p.id,
        "text": p.text,
        "category": p.category,
        "intent": p.intent,
        "source": p.source,
        "importance": p.importance,
        "is_active": p.is_active,
        "engines": p.engines,  # None = every engine the project scans
        "created_at": p.created_at,
    }


def _active_count(session, project_id) -> int:
    return session.scalar(
        select(func.count()).select_from(Prompt).where(Prompt.project_id == project_id, Prompt.is_active)
    ) or 0


def _pool_details(session, project) -> dict | None:
    """Who holds the workspace's question pool when it is full, else None."""
    ent = entitlements(session, project.workspace_id)
    if active_prompts(session, project.workspace_id) < ent.active_prompts:
        return None
    return pool_full_details(session, project.workspace_id, ent.active_prompts)


def _require_prompt_room(session, project) -> None:
    require_active(entitlements(session, project.workspace_id))
    details = _pool_details(session, project)
    if details:
        message = pool_full_message(details, project.id)
        raise AppError(409, "PROMPT_LIMIT", message, limit="active_prompts", details=details)
    if _active_count(session, project.id) >= settings.max_active_prompts:  # hard ceiling per project
        raise AppError(409, "PROMPT_LIMIT", f"A project can track up to {settings.max_active_prompts} active prompts.")


def _pool_full(session, project, created) -> dict | None:
    """Set when new questions were saved switched off because the plan's pool is full, so the UI can say why."""
    if all(p.is_active for p in created):
        return None
    details = _pool_details(session, project)
    return details and {**details, "message": pool_full_message(details, project.id)}


@router.post("/generate")
def generate(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_active(entitlements(session, project.workspace_id))  # generation calls the LLM
        check_budget(session, project.workspace_id)
        created = PromptDiscoveryService().generate_for_project(session, project)
        session.commit()
        prompts = session.scalars(select(Prompt).where(Prompt.project_id == project.id).order_by(Prompt.id)).all()
        return {"created": len(created), "prompts": [serialize(p) for p in prompts], "pool_full": _pool_full(session, project, created)}


@router.post("/suggest")
def suggest(project_id: UUID, request: PromptSuggest, current_user: User = Depends(get_current_user)):
    """New prompts written to the user's instructions. Nothing is saved until they accept some."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_pro(entitlements(session, project.workspace_id), "More prompts")
        check_budget(session, project.workspace_id)
        prompts = PromptDiscoveryService().suggest(session, project, request.instructions.strip(), request.count)
        return {"prompts": prompts}


@router.post("/accept")
def accept(project_id: UUID, request: PromptsAccept, current_user: User = Depends(get_current_user)):
    """Adds the suggested prompts the user kept."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_pro(entitlements(session, project.workspace_id), "More prompts")
        created = PromptDiscoveryService().add_many(session, project, [p.model_dump() for p in request.prompts])
        session.commit()
        return {"created": len(created), "inactive": sum(not p.is_active for p in created), "prompts": [serialize(p) for p in created], "pool_full": _pool_full(session, project, created)}


@router.get("")
def list_prompts(
    project_id: UUID,
    category: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        query = select(Prompt).where(Prompt.project_id == project.id)
        if category:
            query = query.where(Prompt.category == category.upper())
        if status == "active":
            query = query.where(Prompt.is_active)
        elif status == "inactive":
            query = query.where(Prompt.is_active.is_(False))
        return [serialize(p) for p in session.scalars(query.order_by(Prompt.id)).all()]


@router.post("")
def add_prompt(project_id: UUID, request: PromptCreate, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        text = request.text.strip()
        duplicate = session.scalar(
            select(Prompt).where(Prompt.project_id == project.id, func.lower(Prompt.text) == text.lower())
        )
        if duplicate:
            raise AppError(409, "PROMPT_DUPLICATE", "This prompt already exists.")
        require_pro(entitlements(session, project.workspace_id), "Your own prompts")
        _require_prompt_room(session, project)
        prompt = Prompt(project_id=project.id, text=text, category=request.category, intent=request.intent, source="user")
        session.add(prompt)
        session.commit()
        session.refresh(prompt)
        return serialize(prompt)


def _owned_prompt(session, project_id, prompt_id) -> Prompt:
    prompt = session.scalar(select(Prompt).where(Prompt.id == prompt_id, Prompt.project_id == project_id))
    if not prompt:
        raise AppError(404, "PROMPT_NOT_FOUND", "Prompt not found.")
    return prompt


@router.patch("/{prompt_id}")
def update_prompt(
    project_id: UUID, prompt_id: int, request: PromptUpdate, current_user: User = Depends(get_current_user)
):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        prompt = _owned_prompt(session, project.id, prompt_id)
        if request.is_active and not prompt.is_active:
            _require_prompt_room(session, project)
        for field in ("text", "category", "intent", "is_active"):
            value = getattr(request, field)
            if value is not None:
                setattr(prompt, field, value.strip() if isinstance(value, str) else value)
        if request.engines is not None:
            prompt.engines = request.engines or None
        session.commit()
        session.refresh(prompt)
        return serialize(prompt)


@router.delete("/{prompt_id}")
def delete_prompt(project_id: UUID, prompt_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        session.delete(_owned_prompt(session, project.id, prompt_id))
        session.commit()
        return {"message": "Prompt deleted successfully"}
