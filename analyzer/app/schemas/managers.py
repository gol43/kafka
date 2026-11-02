from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ManagerRole = Literal[
    "EFS_VIP_KM",
    "EFS_AKM_VIP",
    "EFS_VIP_DSB",
    "EFS_VIP_TFS",
]


class ManagerProfile(BaseModel):
    """Менеджер и его единственная роль на расчётную дату."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    manager_id: str = Field(alias="managerId")
    role: ManagerRole

    @field_validator("manager_id")
    @classmethod
    def normalize_manager_id(cls, value: str) -> str:
        if not value.isdigit() or len(value) > 8:
            raise ValueError("manager_id должен содержать не больше восьми цифр")
        return value.zfill(8)
