from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.jwt import decode_access_token
from app.common.database import SessionLocal
from app.users.models import User


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    token = credentials.credentials

    try:
        user_id = decode_access_token(token)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        )

    with SessionLocal() as session:
        user = session.scalar(
            select(User).where(User.id == user_id)
        )

        if not user:
            raise HTTPException(
                status_code=401,
                detail="User not found",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=401,
                detail="User is inactive",
            )

        return user