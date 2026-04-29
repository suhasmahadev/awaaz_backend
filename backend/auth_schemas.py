from pydantic import BaseModel, EmailStr
from typing import Optional

class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    role: str = "citizen"   # citizen | admin | moderator | faculty

class NGORegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    org_name: str
    org_type: str
    region: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    user_id: Optional[str] = None
    org_name: Optional[str] = None
    org_type: Optional[str] = None
    region: Optional[str] = None

class AnonRequest(BaseModel):
    fingerprint: str
