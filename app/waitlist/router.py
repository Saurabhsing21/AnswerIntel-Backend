from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.dialects.postgresql import insert

from app.common.database import SessionLocal
from app.common.ratelimit import limit_waitlist
from app.waitlist.models import WaitlistSignup

router = APIRouter(prefix="/waitlist", tags=["Waitlist"])


class WaitlistRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def strip(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.post("", dependencies=[Depends(limit_waitlist)])
def join_waitlist(payload: WaitlistRequest):
    with SessionLocal() as session:
        # Same answer whether or not the address was already there: no way to probe who signed up.
        session.execute(
            insert(WaitlistSignup).values(email=str(payload.email).lower()).on_conflict_do_nothing(index_elements=["email"])
        )
        session.commit()
    return {"ok": True}
