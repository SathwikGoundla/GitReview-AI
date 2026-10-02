from pydantic import BaseModel, Field


class ChecklistCompletionRequest(BaseModel):
    completed: bool = Field(description="True to mark as complete, false to unmark")


class ChecklistCompletionResponse(BaseModel):
    item_id: str
    completed: bool
