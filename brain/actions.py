from enum import Enum
from typing import Union, Optional, Literal, Annotated
from pydantic import BaseModel, Field

class ActionType(str, Enum):
    INSERT_BLOCK = "insert_block"
    MOVE_FLEXIBLE = "move_flexible"
    UPDATE_NOTION = "update_notion"
    NOTIFY_SCHEDULER = "notify_scheduler"
    SEND_REPLY = "send_reply"
    SWITCH_PROVIDER = "switch_provider"
    QUERY_DATABASE = "query_database"

class BaseAction(BaseModel):
    """Base class for all discrete system actions."""
    pass

class InsertBlock(BaseAction):
    action_type: Literal[ActionType.INSERT_BLOCK] = ActionType.INSERT_BLOCK
    subject: str = Field(..., description="Subject to insert (e.g. Physics)")
    duration_mins: int = Field(..., description="Duration in minutes")
    block_type: str = Field(..., description="Type of block, e.g. Revision or Mock")

class MoveFlexibleBlocks(BaseAction):
    action_type: Literal[ActionType.MOVE_FLEXIBLE] = ActionType.MOVE_FLEXIBLE
    hours_shifted: float = Field(..., description="Number of hours to push schedule")

class UpdateNotion(BaseAction):
    action_type: Literal[ActionType.UPDATE_NOTION] = ActionType.UPDATE_NOTION
    target_database: str = Field(..., description="Which DB to update (db1, db2, db3)")
    payload: dict = Field(..., description="Data to write")

class NotifyScheduler(BaseAction):
    action_type: Literal[ActionType.NOTIFY_SCHEDULER] = ActionType.NOTIFY_SCHEDULER
    message: str = Field(..., description="Message for the background scheduler")

class SendReply(BaseAction):
    action_type: Literal[ActionType.SEND_REPLY] = ActionType.SEND_REPLY
    message: str = Field(..., description="Text reply to send to the user")

class SwitchProvider(BaseAction):
    action_type: Literal[ActionType.SWITCH_PROVIDER] = ActionType.SWITCH_PROVIDER
    provider: str = Field(..., description="Provider name (e.g. groq, gemini)")

class QueryDatabase(BaseAction):
    action_type: Literal[ActionType.QUERY_DATABASE] = ActionType.QUERY_DATABASE
    query: str = Field(..., description="Query intent for the database tool")

Action = Annotated[
    Union[
        InsertBlock, 
        MoveFlexibleBlocks, 
        UpdateNotion, 
        NotifyScheduler, 
        SendReply, 
        SwitchProvider, 
        QueryDatabase
    ], 
    Field(discriminator="action_type")
]

class ActionResult(BaseModel):
    """Deterministic result of executing a single action."""
    success: bool = Field(..., description="Whether the action succeeded")
    reason: Optional[str] = Field(None, description="Why it succeeded or failed")
    retry: bool = Field(False, description="Should the executor try again?")
    rollback_needed: bool = Field(False, description="Did it partially fail and require rollback?")

class AssistantRequest(BaseModel):
    """The master output of the Planner, representing a full Execution Plan."""
    intent: str = Field(..., description="The high-level intent classified")
    reasoning: str = Field(..., description="Why these actions were chosen")
    confidence: Literal["high", "medium", "low"] = Field("high", description="Planner's confidence in this plan")
    requires_confirmation: bool = Field(False, description="Should we ask the user before executing?")
    policy_result: Optional[str] = Field(None, description="Result of policy evaluation, e.g., 'Allowed' or 'Rejected'")
    actions: list[Action] = Field(..., description="Ordered list of deterministic actions to execute")
