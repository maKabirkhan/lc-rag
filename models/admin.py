from pydantic import BaseModel, EmailStr

class CreateAdminRequest(BaseModel):
    email: str
    password: str
    full_name: str

class UpdateRoleRequest(BaseModel):
    uid: str 

class DeleteUserRequest(BaseModel):
    uid: str 

class UpdateUsernameRequest(BaseModel):
    uid: str
    new_name: str

class InviteUserRequest(BaseModel):
    email: EmailStr
    role: str

class SendEmailRequest(BaseModel):
    from_email: EmailStr
    subject: str
    body: str