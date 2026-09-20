from typing import Literal

from pydantic import BaseModel

from app.config import DataMode, EgressMode


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    data_mode: DataMode
    egress_mode: EgressMode
