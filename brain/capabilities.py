import time
import json
import asyncio
import logging
from typing import Any

from sentinel.bot.schemas import CapabilitySnapshot
from sentinel.config import FAST_PROVIDERS, THINK_PROVIDERS, FALLBACK_CHAIN

logger = logging.getLogger("sentinel.brain.capabilities")

class CapabilityRegistry:
    """Manages AI provider health, benchmarking, and rankings."""
    
    def __init__(self, state_db):
        self.state = state_db
        
    async def get_snapshot(self) -> CapabilitySnapshot | None:
        """Fetch the latest capability snapshot from the database."""
        raw = await self.state.get_state("provider_benchmarks")
        if not raw:
            return None
        try:
            return CapabilitySnapshot.model_validate_json(raw)
        except Exception as e:
            logger.warning(f"Failed to parse capability snapshot: {e}")
            return None
            
    async def is_stale(self, hours: int = 6) -> bool:
        """Check if the cache is older than the specified hours."""
        snap = await self.get_snapshot()
        if not snap:
            return True
        return (time.time() - snap.timestamp) > (hours * 3600)
        
    async def get_cached_ranking(self, tier: str) -> list[str]:
        """Get the cached ranking for a tier, falling back to defaults if empty."""
        snap = await self.get_snapshot()
        if not snap:
            return FAST_PROVIDERS if tier == "fast" else THINK_PROVIDERS
            
        if tier == "fast" and snap.fast_rankings:
            return snap.fast_rankings
        elif tier == "think" and snap.think_rankings:
            return snap.think_rankings
            
        return FAST_PROVIDERS if tier == "fast" else THINK_PROVIDERS

    async def run_benchmark(self, ai_engine) -> None:
        """Perform a background ping on all providers and update the rankings cache."""
        logger.info("Starting background provider benchmark...")
        
        # We will use health_check_all and timing to measure latency
        stats: dict[str, dict[str, Any]] = {}
        
        async def _ping_provider(provider: str):
            start = time.time()
            try:
                # Dispatch a very simple prompt
                await ai_engine._dispatch(provider, "ping", "Reply with 'pong'.", 0.0, 16)
                latency = time.time() - start
                stats[provider] = {"success": True, "latency": latency}
            except Exception as e:
                stats[provider] = {"success": False, "latency": 999.0, "error": str(e)}

        # Run concurrently
        await asyncio.gather(*[_ping_provider(p) for p in FALLBACK_CHAIN])
        
        # Build new rankings
        def _rank(providers: list[str]) -> list[str]:
            # Sort by success (True first), then by latency (lowest first)
            return sorted(
                providers,
                key=lambda p: (not stats.get(p, {}).get("success", False), stats.get(p, {}).get("latency", 999.0))
            )
            
        fast_ranked = _rank(FAST_PROVIDERS)
        think_ranked = _rank(THINK_PROVIDERS)
        
        snapshot = CapabilitySnapshot(
            timestamp=time.time(),
            fast_rankings=fast_ranked,
            think_rankings=think_ranked,
            provider_stats=stats
        )
        
        # Save to Mongo
        await self.state.set_state("provider_benchmarks", snapshot.model_dump_json())
        logger.info("Background provider benchmark complete and cached.")
