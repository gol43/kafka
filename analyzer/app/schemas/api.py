from pydantic import BaseModel, ConfigDict, Field


class DialogRunRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    call_id: str = Field(min_length=1)


class AcceptedResponse(BaseModel):
    status: str = "accepted"
