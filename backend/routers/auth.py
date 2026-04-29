"""Auth router: login and register."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth_schemas import NGORegister, Token, UserLogin, UserRegister
from auth_security import create_access_token, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def _get_pool(request: Request):
    return request.app.state.pool

def _get_repo(request: Request):
    return request.app.state.repo

def _get_service(request: Request):
    return request.app.state.service


# ── dependency: current user from JWT ──────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    """Validates Bearer JWT and returns user payload dict."""
    from auth_security import decode_token
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, request: Request):
    """Register a new user. Role: citizen | admin | moderator | faculty."""
    if body.role not in ("citizen", "admin", "moderator", "faculty"):
        raise HTTPException(status_code=422, detail="role must be citizen, admin, moderator, or faculty")
    try:
        user = await _get_service(request).register_user(
            name=body.name, email=body.email, password=body.password, role=body.role
        )
        return {"message": "registered", "user_id": user["id"], "role": user["role"]}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/ngo-register", status_code=status.HTTP_201_CREATED)
async def ngo_register(body: NGORegister, request: Request):
    """Register an NGO or contractor org account for later /auth/login."""
    org_type = body.org_type.lower().strip()
    if org_type not in ("ngo", "contractor"):
        raise HTTPException(status_code=422, detail="org_type must be ngo or contractor")

    role = "faculty" if org_type == "ngo" else "moderator"
    try:
        user = await _get_service(request).register_user(
            name=body.name,
            email=body.email,
            password=body.password,
            role=role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    async with _get_pool(request).acquire() as conn:
        await conn.execute(
            """
            INSERT INTO org_profiles(user_id,org_name,org_type,region)
            VALUES($1,$2,$3,$4)
            ON CONFLICT(user_id) DO UPDATE
              SET org_name=$2, org_type=$3, region=$4
            """,
            user["id"],
            body.org_name,
            org_type,
            body.region,
        )

    return {
        "message": "registered",
        "user_id": user["id"],
        "role": role,
        "org_type": org_type,
    }


@router.post("/login", response_model=Token)
async def login(body: UserLogin, request: Request):
    """Authenticate and return JWT."""
    user = await _get_service(request).get_user_by_email(body.email)
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({"sub": user["id"], "role": user["role"], "email": user["email"]})
    profile = None
    async with _get_pool(request).acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT org_name, org_type, region FROM org_profiles WHERE user_id=$1",
            user["id"],
        )
    profile_data = dict(profile) if profile else {}
    return Token(
        access_token=token,
        role=user["role"],
        username=user["name"],
        user_id=user["id"],
        org_name=profile_data.get("org_name"),
        org_type=profile_data.get("org_type"),
        region=profile_data.get("region"),
    )


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"user_id": current_user.get("sub"), "role": current_user.get("role")}
