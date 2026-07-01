"""
SENTINEL Configuration — Central configuration hub.
All API keys loaded from environment variables for security.
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# PROJECT PATHS
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "data" / "sentinel.db"
LOG_PATH = PROJECT_ROOT / "data" / "sentinel.log"
SENTINEL_VERSION = "phase8.2"


def _load_dotenv(env_path: Path) -> None:
    """Load simple KEY=value pairs from .env without overriding real env vars."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key or key in os.environ:
            continue

        if value[:1] in {"'", '"'}:
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = value.split("#", 1)[0].strip()

        os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # Set after first /start
TELEGRAM_ALLOWED_USERS = [u.strip() for u in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",") if u.strip()]

# ─────────────────────────────────────────────────────────────────────────────
# NOTION
# ─────────────────────────────────────────────────────────────────────────────
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_VERSION = "2022-06-28"

# Database IDs
NOTION_DB1_ID = os.environ.get("NOTION_DB1_ID", "36dbc6be-f0c2-81db-9da5-f2d1856408ae")  # Daily Execution Ledger
NOTION_DB2_ID = os.environ.get("NOTION_DB2_ID", "36dbc6be-f0c2-81fe-a1d9-ee8def93d63e")  # Revision Backlog
NOTION_DB3_ID = os.environ.get("NOTION_DB3_ID", "36dbc6be-f0c2-81ba-a6bd-f3e39886eb50")  # Error Log
NOTION_DB4_ID = os.environ.get("NOTION_DB4_ID", "")       # System Log (created on first run)

# ─────────────────────────────────────────────────────────────────────────────
# MONGODB
# ─────────────────────────────────────────────────────────────────────────────
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "sentinel_brain")

# ─────────────────────────────────────────────────────────────────────────────
# AI API KEYS (Tiered)
# ─────────────────────────────────────────────────────────────────────────────
AI_PROVIDERS = {
    "gemini": {
        "api_key_env": "GOOGLE_API_KEY",
        "tier": "think",
        "model": "gemini-2.5-pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "rpm_limit": 15,
    },
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "tier": "fast",
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "rpm_limit": 30,
    },
    "cerebras": {
        "api_key_env": "CEREBRAS_API_KEY",
        "tier": "fast",
        "model": "gpt-oss-120b",
        "base_url": "https://api.cerebras.ai/v1",
        "rpm_limit": 30,
    },
    "openrouter": {
        "api_key_env": "OPENROUTER_API_KEY",
        "tier": "fallback",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "base_url": "https://openrouter.ai/api/v1",
        "rpm_limit": 20,
    },
    "cohere": {
        "api_key_env": "COHERE_API_KEY",
        "tier": "fallback",
        "model": "command-a-plus-05-2026",
        "base_url": "https://api.cohere.com/v2",
        "rpm_limit": 20,
    },
    "huggingface": {
        "api_key_env": "HUGGINGFACE_API_KEY",
        "tier": "fallback",
        "model": "meta-llama/Meta-Llama-3-70B-Instruct",
        "base_url": "https://api-inference.huggingface.co/models",
        "rpm_limit": 10,
    },
    "cloudflare": {
        "api_key_env": "CLOUDFLARE_API_KEY",
        "tier": "fallback",
        "model": "@cf/meta/llama-3.1-70b-instruct",
        "base_url": None,  # Cloudflare Workers AI uses a different format
        "rpm_limit": 10,
    },
    "cf_glm_5_2": {
        "api_key_env": "CLOUDFLARE_API_KEY",
        "tier": "think",
        "model": "@cf/zai-org/glm-5.2",
        "base_url": None,
        "rpm_limit": 10,
    },
    "cf_gpt_oss_120b": {
        "api_key_env": "CLOUDFLARE_API_KEY",
        "tier": "fast",
        "model": "@cf/openai/gpt-oss-120b",
        "base_url": None,
        "rpm_limit": 10,
    },
    "cf_nemotron_120b": {
        "api_key_env": "CLOUDFLARE_API_KEY",
        "tier": "fast",
        "model": "@cf/nvidia/nemotron-3-120b-a12b",
        "base_url": None,
        "rpm_limit": 10,
    },
    "g4f_pro": {
        "api_key_env": "G4F_API_KEY",
        "tier": "think",
        "model": "gpt-4o",
        "base_url": "https://api.g4f.dev/v1",
        "rpm_limit": 30,
    },
    "g4f": {
        "api_key_env": "G4F_API_KEY",
        "tier": "fast",
        "model": "gpt-4o-mini",
        "base_url": "https://api.g4f.dev/v1",
        "rpm_limit": 30,
    },
    "gpt_5_5": {
        "api_key_env": "G4F_API_KEY",
        "tier": "think",
        "model": "gpt-5.5",
        "base_url": "https://api.g4f.dev/v1",
        "rpm_limit": 30,
    },
    "glm_5_2": {
        "api_key_env": "G4F_API_KEY",
        "tier": "think",
        "model": "glm-5.2",
        "base_url": "https://api.g4f.dev/v1",
        "rpm_limit": 30,
    },
    "gpt_oss_120b": {
        "api_key_env": "G4F_API_KEY",
        "tier": "fast",
        "model": "openai/gpt-oss-120b",
        "base_url": "https://api.g4f.dev/v1",
        "rpm_limit": 30,
    },
    "groq_oss_120b": {
        "api_key_env": "GROQ_API_KEY",
        "tier": "fast",
        "model": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1",
        "rpm_limit": 30,
    },
    "uncloseai": {
        "api_key_env": "UNCLOSEAI_API_KEY",
        "tier": "fallback",
        "model": "claude-3-haiku",
        "base_url": "https://api.uncloseai.com/v1",
        "rpm_limit": 20,
    },
    "ollama": {
        "api_key_env": "OLLAMA_API_KEY", # Can be left blank for ollamafreeapi
        "tier": "fast",
        "model": "qwen3.5:122b-cloud",
        "base_url": "http://127.0.0.1:11434/v1",
        "rpm_limit": 60,
    },
}

# Fallback chain order
FALLBACK_CHAIN = ["gpt_5_5", "cohere", "cf_glm_5_2", "glm_5_2", "g4f_pro", "gemini", "gpt_oss_120b", "groq_oss_120b", "cf_gpt_oss_120b", "cf_nemotron_120b", "g4f", "groq", "cerebras", "ollama", "openrouter", "huggingface", "uncloseai", "cloudflare"]
FAST_PROVIDERS = ["groq_oss_120b", "cerebras", "cf_gpt_oss_120b", "cf_nemotron_120b", "gpt_oss_120b", "g4f", "groq", "ollama"]
THINK_PROVIDERS = ["gpt_5_5", "cf_glm_5_2", "glm_5_2", "g4f_pro", "gemini"]

# Task Profiles for dynamic routing and execution strategy
DEFAULT_TASK_PROFILES = {
    "parse_message": {
        "priority": "high", "quality_target": 6, "latency_budget": 2, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "benchmark_judge": {
        "priority": "high", "quality_target": 10, "latency_budget": 300, 
        "background": False, "allow_benchmark": True, "allow_synthesis": False,
        "temperature": 0.0
    },
    "think": {
        "priority": "high", "quality_target": 9, "latency_budget": 30, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "fast": {
        "priority": "medium", "quality_target": 7, "latency_budget": 5, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "fast_decision": {
        "priority": "medium", "quality_target": 7, "latency_budget": 5, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "evening_reflection": {
        "priority": "high", "quality_target": 8, "latency_budget": 30, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "block_prompt": {
        "priority": "high", "quality_target": 8, "latency_budget": 10, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "timeout_ping": {
        "priority": "medium", "quality_target": 7, "latency_budget": 5, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "general_chat": {
        "priority": "low", "quality_target": 7, "latency_budget": 5, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "general": {
        "priority": "medium", "quality_target": 7, "latency_budget": 5, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "daily_plan": {
        "priority": "high", "quality_target": 8, "latency_budget": 10, 
        "background": False, "allow_benchmark": False, "allow_synthesis": False
    },
    "weekly_roast": {
        "priority": "high", "quality_target": 10, "latency_budget": 300, 
        "background": True, "allow_benchmark": True, "allow_synthesis": True,
        "preferred_models": ["gpt_5_5", "gemini"]
    },
    "test_recalibration": {
        "priority": "high", "quality_target": 9, "latency_budget": 60, 
        "background": True, "allow_benchmark": True, "allow_synthesis": True
    },
    "revision_analysis": {
        "priority": "high", "quality_target": 10, "latency_budget": 120, 
        "background": True, "allow_benchmark": True, "allow_synthesis": True
    },
    "trend_detection": {
        "priority": "medium", "quality_target": 9, "latency_budget": 120, 
        "background": True, "allow_benchmark": True, "allow_synthesis": True
    },
    "benchmark": {
        "priority": "low", "quality_target": 10, "latency_budget": 0, 
        "background": True, "allow_benchmark": True, "allow_synthesis": False
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# STUDY SYSTEM CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
DAILY_CY_TARGET = 240
HARD_STOP_HOUR = 1  # 01:00 AM
MORNING_BRIEFING_HOUR = 8  # 08:00 AM
TIMEZONE = "Asia/Kolkata"

# Target: IIT Bombay CS
TARGET_IIT = "IIT Bombay"
TARGET_BRANCH = "Computer Science"
TARGET_JEE_SCORE = 320  # out of 360 (approximate cutoff)

# Bot personality
BOT_NAME = "SENTINEL"
BOT_PERSONALITY = "competitive_rival"

# ─────────────────────────────────────────────────────────────────────────────
# t_q LOOKUP TABLE: (exercise_type, subject) -> minutes per question
# ─────────────────────────────────────────────────────────────────────────────
T_Q_TABLE = {
    "JMYL":  {"Chem": 4,    "Physics": 4,    "Maths": 4,    "_default": 4},
    "JAYL":  {"Chem": 8,    "Physics": 8,    "Maths": 8,    "_default": 8},
    "PYQs":  {"Chem": 4.5,  "Physics": 4.5,  "Maths": 4.5,  "_default": 4.5},
    "Ex 1A": {"Chem": 2.0,  "Physics": 2.5,  "Maths": 4.5,  "_default": 3.0},
    "Ex 1B": {"Chem": 2.5,  "Physics": 3.5,  "Maths": 6.0,  "_default": 4.0},
    "Ex 2A": {"Chem": 2.5,  "Physics": 4.5,  "Maths": 6.5,  "_default": 4.5},
    "Ex 2B": {"Chem": 2.5,  "Physics": 4.5,  "Maths": 6.5,  "_default": 4.5},
    "MLE":   {"Chem": 3.0,  "Physics": 5.0,  "Maths": 5.5,  "_default": 4.5},
    "Ex 4A": {"Chem": 10.0, "Physics": 13.0, "Maths": 15.0, "_default": 12.0},
    "Ex 4B": {"Chem": 10.0, "Physics": 13.0, "Maths": 15.0, "_default": 12.0},
    "Ex 3A": {"Chem": 12.0, "Physics": 15.0, "Maths": 18.0, "_default": 15.0},
    "Ex 3B": {"Chem": 12.0, "Physics": 15.0, "Maths": 18.0, "_default": 15.0},
}
SUBJECTS = ["Physics", "Chem", "Maths"]
EXERCISE_TYPES = list(T_Q_TABLE.keys())
# Block types for scheduling
BLOCK_TYPES = [
    "EB-1", "EB-2", "EB-3", "EB - A", "EB - B", "EB-C",
    "RB", "TA", "ADV.", "AB"
]

# ─────────────────────────────────────────────────────────────────────────────
# TIMING CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
BLOCK_TIMEOUT_MINUTES = 15       # Minutes after expected end before timeout ping
RESPONSE_TIMEOUT_MINUTES = 30    # Minutes of silence before "are you ok?" check
MAX_PACING_L1 = 5                # Max minutes per Level 1 question (from protocol)
MAX_PACING_L2 = 8                # Max minutes per Level 2 question (from protocol)

# API health check intervals
API_HEALTH_CHECK_HOURS = 2
NOTION_HEALTH_CHECK_HOURS = 6

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: get API key from environment
# ─────────────────────────────────────────────────────────────────────────────
def get_api_key(provider: str) -> str:
    """Get the API key for a given provider from environment variables."""
    env_var = AI_PROVIDERS.get(provider, {}).get("api_key_env", "")
    return os.environ.get(env_var, "")

def validate_config() -> list[str]:
    """Validate that essential config values are present. Returns list of errors."""
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN not set")
    if not NOTION_API_KEY:
        errors.append("NOTION_API_KEY not set")
    
    # Check at least one AI provider has a key
    has_ai = False
    for provider in FALLBACK_CHAIN:
        if get_api_key(provider):
            has_ai = True
            break
    if not has_ai:
        errors.append("No AI API keys configured")
    
    return errors
