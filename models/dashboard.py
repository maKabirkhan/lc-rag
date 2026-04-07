from pydantic import BaseModel, Field, HttpUrl
from typing import Optional

class CreateDashboardRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    category: str = Field(..., min_length=1, max_length=50)
    dashboard_link: HttpUrl

class UpdateDashboardRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    dashboard_link: Optional[HttpUrl] = None
