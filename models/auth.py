from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class SignUpRequest(BaseModel):
    full_name: Optional[str] = Field(None)
    email: EmailStr = Field(...)
    password: Optional[str] = Field(None, min_length=6)
    confirm_password: Optional[str] = Field(None, min_length=6)
    role: str = Field(default="user", description="Role can be 'user' or 'admin'")
    is_google: bool = Field(default=False, description="True for Google sign-in, False for email/password")

class SigninRequest(BaseModel):
    email: EmailStr = Field(...)
    password: Optional[str] = Field(None)
    role: str = Field(default="user", description="Role can be 'user' or 'admin'")
    is_google: bool = Field(default=False, description="True for Google sign-in, False for email/password")

class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(...)

class RefreshTokenRequest(BaseModel):
    refresh: str

class UpdateRequest(BaseModel):
    full_name: str | None = Field(None)
    email: EmailStr | None = Field(None)

class UpdatePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=6)
    new_password: str = Field(..., min_length=6)
    confirm_new_password: str = Field(..., min_length=6)
