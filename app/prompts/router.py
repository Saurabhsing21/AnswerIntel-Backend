from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_active, require_room
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.prompts.models import Prompt
from app.prompts.schemas import PromptCreate, PromptUpdate
from app.prompts.service import PromptDiscoveryService
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
        "created_at": p.created_at,
    }


def _active_count(session, project_id) -> int:
    return session.scalar(
        select(func.count()).select_from(Prompt).where(Prompt.project_id == project_id, Prompt.is_active)
    ) or 0


def _require_prompt_room(session, project) -> None:
    ent = entitlements(session, project.workspace_id)
    message = f"You can track up to {ent.active_prompts} active prompts."
    require_room(ent, "active_prompts", _active_count(session, project.id), message, "PROMPT_LIMIT", 409)


@router.post("/generate")
def generate(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_active(entitlements(session, project.workspace_id))  # generation calls the LLM
        created = PromptDiscoveryService().generate_for_project(session, project)
        session.commit()
        prompts = session.scalars(select(Prompt).where(Prompt.project_id == project.id).order_by(Prompt.id)).all()
        return {"created": len(created), "prompts": [serialize(p) for p in prompts]}


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
