from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.auth.password import hash_password
from app.auth.schemas import RegisterRequest
from app.common.database import SessionLocal
from app.users.models import User
from app.auth.schemas import LoginRequest, RegisterRequest
from app.auth.password import hash_password, verify_password
from app.auth.jwt import create_access_token
from fastapi import Depends
from app.auth.dependencies import get_current_user
from app.common.ratelimit import limit_login


router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register")
def register(request: RegisterRequest):
    with SessionLocal() as session:
        existing_user = session.scalar(
            select(User).where(User.email == request.email)
        )

        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Email already registered",
            )

        user = User(
            email=request.email,
            password_hash=hash_password(request.password),
        )

        session.add(user)
        session.commit()
        session.refresh(user)

        return {
            "id": user.id,
            "email": user.email,
        }



@router.post("/login", dependencies=[Depends(limit_login)])
def login(request: LoginRequest):
    with SessionLocal() as session:
        user = session.scalar(
            select(User).where(User.email == request.email)
        )

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        if not verify_password(
            request.password,
            user.password_hash,
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        access_token = create_access_token(user.id)

        return {
            "access_token": access_token,
            "token_type": "bearer",
        }

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
    }