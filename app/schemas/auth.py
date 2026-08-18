from pydantic import BaseModel, ConfigDict


class ProvidersResponse(BaseModel):
    providers: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 초


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    role: str
