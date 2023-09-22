from typing import List

from pydantic import BaseModel

from dstack._internal.core.models.runs import RunSpec


class GetRunRequest(BaseModel):
    run_name: str


class GetRunPlanRequest(BaseModel):
    run_spec: RunSpec


class SubmitRunRequest(BaseModel):
    run_spec: RunSpec


class StopRunsRequest(BaseModel):
    runs_names: List[str]
    abort: bool


class DeleteRunsRequest(BaseModel):
    runs_names: List[str]