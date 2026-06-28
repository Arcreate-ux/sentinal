import os
import subprocess
from typing import Any

class SystemTools:
    """Provides deterministic system-level tools for the AI agent to execute."""
    
    def __init__(self, state_db):
        self.state = state_db
        
    async def get_db_stats(self) -> dict[str, Any]:
        """Returns actual MongoDB memory and storage metrics."""
        return await self.state.get_db_stats()
        
    def get_system_logs(self, lines: int = 50) -> str:
        """Reads the last N lines of the sentinel.log file."""
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sentinel.log")
        if not os.path.exists(log_path):
            return "No log file found."
            
        try:
            # Using standard tail for fast large file reading
            result = subprocess.run(["tail", "-n", str(lines), log_path], capture_output=True, text=True, check=True)
            return result.stdout
        except Exception as e:
            return f"Error reading logs: {e}"
            
    def get_api_health(self, ai_engine) -> dict[str, Any]:
        """Returns the health and success metrics of AI providers."""
        return ai_engine.get_stats_summary()
