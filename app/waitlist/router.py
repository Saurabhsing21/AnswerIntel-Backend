from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.dialects.postgresql import insert

from app.common.database import SessionLocal
from app.common.ratelimit import limit_waitlist
from app.waitlist.email import send_welcome
from app.waitlist.models import WaitlistSignup

router = APIRouter(prefix="/waitlist", tags=["Waitlist"])


class WaitlistRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def strip(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.post("", dependencies=[Depends(limit_waitlist)])
def join_waitlist(payload: WaitlistRequest, background_tasks: BackgroundTasks):
    email = str(payload.email).lower()
    with SessionLocal() as session:
        # Same answer whether or not the address was already there: no way to probe who signed up.
        new = session.execute(
            insert(WaitlistSignup).values(email=email).on_conflict_do_nothing(index_elements=["email"]).returning(WaitlistSignup.id)
        ).first()
        session.commit()
    if new:  # first time only, after the response is sent
        background_tasks.add_task(send_welcome, email)
    return {"ok": True}
