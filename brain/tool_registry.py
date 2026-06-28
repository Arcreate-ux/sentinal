"""
SENTINEL — Tool Registry (brain/tool_registry.py)

Central source of truth for available actions.
Each tool defines its capabilities, schema, and how to execute/rollback safely.
"Every abstraction must pay rent." -> Keep it simple, but robust enough for the compiler.
"""

from typing import Any, Dict, Type, Optional
from pydantic import BaseModel, Field

class ToolResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    rollback_needed: bool = False

class BaseTool:
    """Base interface for all tools."""
    name: str = "base_tool"
    description: str = "Base description"
    input_schema: Type[BaseModel] = BaseModel
    
    async def execute(self, params: BaseModel, context: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError
        
    async def rollback(self, params: BaseModel, context: Dict[str, Any]) -> bool:
        """Undo the operation if supported."""
        return False

# ── Concrete Tools ──

class SendReplySchema(BaseModel):
    message: str = Field(..., description="The message to send to the user.")

class SendReplyTool(BaseTool):
    name = "send_reply"
    description = "Send a text reply to the user."
    input_schema = SendReplySchema

    async def execute(self, params: SendReplySchema, context: Dict[str, Any]) -> ToolResult:
        reply_callback = context.get("reply_callback")
        if not reply_callback:
            return ToolResult(success=False, error="No reply callback provided.")
        try:
            await reply_callback(params.message)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

class UpdateNotionSchema(BaseModel):
    target_database: str = Field(..., description="db1, db2, or db3")
    payload: Dict[str, Any] = Field(..., description="Data payload")

class UpdateNotionTool(BaseTool):
    name = "update_notion"
    description = "Write or update records in Notion DBs."
    input_schema = UpdateNotionSchema

    async def execute(self, params: UpdateNotionSchema, context: Dict[str, Any]) -> ToolResult:
        notion_client = context.get("notion_client")
        if not notion_client:
            return ToolResult(success=False, error="Notion client not found in context.")
            
        try:
            if params.target_database == "db1":
                # Assuming payload matches create_db1_row kwargs
                await notion_client.create_db1_row(**params.payload)
                return ToolResult(success=True, data={"status": "notion_updated", "db": "db1"})
            elif params.target_database in ["db2", "db3"]:
                await notion_client.update_db2_db3(params.payload)
                return ToolResult(success=True, data={"status": "notion_updated", "db": params.target_database})
            else:
                return ToolResult(success=False, error="Invalid target database")
        except Exception as e:
            return ToolResult(success=False, error=str(e), rollback_needed=True)

class SwitchProviderSchema(BaseModel):
    provider: str = Field(..., description="Name of the AI provider")

class SwitchProviderTool(BaseTool):
    name = "switch_provider"
    description = "Switch the active AI provider in Developer Mode."
    input_schema = SwitchProviderSchema

    async def execute(self, params: SwitchProviderSchema, context: Dict[str, Any]) -> ToolResult:
        ai_engine = context.get("ai_engine")
        if not ai_engine:
            return ToolResult(success=False, error="AI Engine missing")
            
        try:
            ai_engine.switch_provider(params.provider)
            return ToolResult(success=True, data={"provider": params.provider})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

# ── Registry ──

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_defaults()
        
    def _register_defaults(self):
        self.register(SendReplyTool())
        self.register(UpdateNotionTool())
        self.register(SwitchProviderTool())
        
    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool
        
    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)
        
    def get_all_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Used by the ActionCompiler or Planner to know what tools exist."""
        schemas = {}
        for name, tool in self._tools.items():
            schemas[name] = {
                "description": tool.description,
                "schema": tool.input_schema.model_json_schema()
            }
        return schemas
