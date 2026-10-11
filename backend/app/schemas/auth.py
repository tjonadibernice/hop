import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
	email: EmailStr
	password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
	token: str


class MessageResponse(BaseModel):
	message: str


class UserResponse(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: uuid.UUID
	email: str
	created_at: datetime
