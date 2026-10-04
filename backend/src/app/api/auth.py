from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import LoginIn, MeOut, RefreshIn, TokenOut
from app.core.db import get_db
from app.models import User
from app.services import auth as auth_service
from app.services.rbac import user_permissions

router = APIRouter(prefix="/auth", tags=["auth"])


def _wrap(fn, *args):
    try:
        return fn(*args)
    except auth_service.AuthError as e:
        raise HTTPException(e.status_code, e.message, headers={"WWW-Authenticate": "Bearer"})


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    return _wrap(auth_service.login, db, body.username, body.password, request)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    return _wrap(auth_service.refresh, db, body.refresh_token, request)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    auth_service.logout(db, body.refresh_token, request)
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        roles=sorted(r.code for r in user.roles),
        permissions=sorted(user_permissions(user)),
    )
