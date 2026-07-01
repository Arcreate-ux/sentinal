"""
SENTINEL AI Engine — The brain's API layer.
Routes AI calls through a tiered provider system with automatic fallback,
retry logic, timeout handling, and per-provider health tracking.

Architecture:
    ┌─────────┐
    │ AIEngine│─── call(task_type, prompt) ──►  _get_providers_for_task()
    └────┬────┘                                       │
         │                                    ┌───────▼────────┐
         │                                    │ Ordered list   │
         │                                    │ of providers   │
         │                                    └───────┬────────┘
         │                                            │
         ▼                                            ▼
    Try provider[0] ──fail──► provider[1] ──fail──► ... ──fail──► AIAllProvidersFailedError
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import AsyncOpenAI

from sentinel.config import (
    AI_PROVIDERS,
    FALLBACK_CHAIN,
    FAST_PROVIDERS,
    THINK_PROVIDERS,
    DEFAULT_TASK_PROFILES,
    get_api_key,
)
from sentinel.bot.schemas import TaskProfile
from sentinel.brain.capabilities import CapabilityRegistry

logger = logging.getLogger("sentinel.brain.ai_engine")

# ─────────────────────────────────────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────────────────────────────────────

class AIProviderError(Exception):
    """A single AI provider failed."""
    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"[{provider}] {reason}")

class AIAllProvidersFailedError(Exception):
    """Every provider in the fallback chain has failed."""
    def __init__(self, errors: list[AIProviderError]) -> None:
        self.errors = errors
        summary = "; ".join(str(e) for e in errors)
        super().__init__(f"All AI providers failed: {summary}")

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER STATS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProviderStats:
    """Runtime health/performance metrics for a single provider."""
    last_call_time: float = 0.0
    failure_count: int = 0
    success_count: int = 0
    total_latency: float = 0.0
    last_error: str = ""
    last_error_time: float = 0.0

    @property
    def avg_latency(self) -> float:
        """Average latency in seconds across successful calls."""
        if self.success_count == 0:
            return 0.0
        return self.total_latency / self.success_count

    def record_success(self, latency: float) -> None:
        self.last_call_time = time.time()
        self.success_count += 1
        self.total_latency += latency
        # Decay failure count on success (provider recovered)
        self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self, error: str) -> None:
        self.last_call_time = time.time()
        self.failure_count += 1
        self.last_error = error
        self.last_error_time = time.time()

# ─────────────────────────────────────────────────────────────────────────────
# AI ENGINE
# ─────────────────────────────────────────────────────────────────────────────

# Timeout and retry constants
_REQUEST_TIMEOUT = 30.0          # seconds per request
_MAX_RETRIES = 2                 # retries per provider (total attempts = 3)
_RETRY_BACKOFF_BASE = 1.5        # exponential backoff base in seconds
_HEALTH_CHECK_TIMEOUT = 10.0     # shorter timeout for health pings

# OpenAI-compatible providers (use the openai SDK)
_OPENAI_COMPATIBLE = {"groq", "cerebras", "openrouter", "g4f", "uncloseai", "g4f_pro", "gpt_5_5", "glm_5_2", "gpt_oss_120b", "groq_oss_120b"}
# Providers that use raw httpx
_HTTPX_PROVIDERS = {"gemini", "cohere", "huggingface", "cloudflare"}

class AIEngine:
    """Routes AI requests through tiered providers with fallback & tracking.
    
    Usage::
        engine = AIEngine()
        response = await engine.call("daily_plan", prompt="Generate today's plan...",
                                     system_prompt=SYSTEM_PROMPT)
    """

    def __init__(self, state_db: Any = None) -> None:
        self._http: httpx.AsyncClient = httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=10.0),
            follow_redirects=True,
        )
        # Per-provider stats
        self.stats: dict[str, ProviderStats] = {
            provider: ProviderStats() for provider in AI_PROVIDERS
        }
        # Lazily-initialized openai clients keyed by provider name
        self._openai_clients: dict[str, AsyncOpenAI] = {}
        self.last_provider_used: str | None = None
        self._developer_force_provider: str | None = None
        
        self.registry = CapabilityRegistry(state_db) if state_db else None
        logger.info("AIEngine initialised — providers: %s", ", ".join(FALLBACK_CHAIN))

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Gracefully shut down HTTP clients."""
        await self._http.aclose()
        for client in self._openai_clients.values():
            await client.close()
        logger.info("AIEngine shut down.")

    # ── public API ────────────────────────────────────────────────────────

    def switch_provider(self, provider: str) -> None:
        """Force the engine to always use this provider (used by Developer Mode)."""
        self._developer_force_provider = provider
        logger.info(f"Developer mode: API routed exclusively to {provider}")

    async def call(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        force_provider: str | None = None,
        force_model: str | None = None,
    ) -> str:
        """Make an AI call, routing to the right tier and falling back on failure.
        
        Args:
            task_type: Key from TASK_ROUTING (e.g. "daily_plan", "parse_message").
            prompt: The user/assistant prompt content.
            system_prompt: Optional system prompt override.
            temperature: Sampling temperature.
            max_tokens: Maximum response tokens.
            force_provider: Explicitly bypass tier routing and use this provider.
            force_model: Explicitly bypass the configured model for the provider.
            
        Returns:
        Returns:
            The AI-generated text response.
            
        Raises:
            AIAllProvidersFailedError: If every provider in the chain fails.
        """
        if self._developer_force_provider:
            force_provider = self._developer_force_provider

        if not force_provider:
            # We construct a TaskProfile object from defaults
            profile_dict = DEFAULT_TASK_PROFILES.get(task_type, DEFAULT_TASK_PROFILES.get("general", {}))
            profile = TaskProfile(task=task_type, **profile_dict)
            
            # 1. Background Intelligence Check
            if self.registry and profile.allow_benchmark and (await self.registry.is_stale(hours=6)):
                logger.info(f"Task '{task_type}' allows benchmarking and cache is stale. Running background benchmark...")
                await self.registry.run_benchmark(self)
                
            # 2. Deep Synthesis Check
            if profile.allow_synthesis and profile.quality_target >= 8 and profile.latency_budget > 60:
                logger.info(f"Task '{task_type}' meets criteria for deep synthesis. Rerouting to call_deep.")
                return await self.call_deep(prompt, system_prompt, max_tokens)

        if force_provider:
            providers = [force_provider.lower()] + [p for p in FALLBACK_CHAIN if p != force_provider.lower()]
        else:
            providers = await self._get_providers_for_task(task_type)
            
        errors: list[AIProviderError] = []

        for provider in providers:
            api_key = get_api_key(provider)
            if not api_key and provider != "ollama":
                logger.debug("Skipping %s — no API key configured.", provider)
                continue

            try:
                text = await self._call_with_retries(
                    provider, prompt, system_prompt, temperature, max_tokens, force_model,
                )
                self.last_provider_used = provider
                return text
            except AIProviderError as exc:
                errors.append(exc)
                logger.warning(
                    "Provider %s failed for task '%s': %s — falling back.",
                    provider, task_type, exc.reason,
                )
                continue

        raise AIAllProvidersFailedError(errors)

    async def health_check_all(self) -> dict[str, bool]:
        """Ping every configured provider with a tiny prompt.
        
        Returns:
            Dict mapping provider name → healthy (bool).
        """
        results: dict[str, bool] = {}

        async def _check(provider: str) -> None:
            api_key = get_api_key(provider)
            if not api_key:
                results[provider] = False
                return
                
            try:
                import asyncio
                await asyncio.wait_for(
                    self._dispatch(
                        provider, "ping", "Reply with 'pong'.", 0.0, 16,
                    ),
                    timeout=_HEALTH_CHECK_TIMEOUT
                )
                results[provider] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("Health check failed for %s: %s", provider, exc)
                results[provider] = False

        await asyncio.gather(*[_check(p) for p in FALLBACK_CHAIN])
        return results

    # ── provider routing ──────────────────────────────────────────────────

    async def _get_providers_for_task(self, task_type: str) -> list[str]:
        """Return ordered provider list based on TaskProfile priority and latency budget.
        
        If latency_budget is small (e.g. < 5s) -> fast tier preferred.
        If priority is high and quality > 7 -> think tier preferred.
        """
        profile_dict = DEFAULT_TASK_PROFILES.get(task_type, DEFAULT_TASK_PROFILES.get("general", {}))
        profile = TaskProfile(task=task_type, **profile_dict)
        
        preferred = []
        # If models are explicitly preferred in the profile, prioritize them
        # Note: preferred_models must use PROVIDER names (e.g. "g4f_pro"), not model names
        if profile.preferred_models:
            preferred.extend([m for m in profile.preferred_models if m in AI_PROVIDERS])
            
        # Dynamically fetch from the registry cache if available, else fallback to defaults
        if self.registry:
            fast_list = (await self.registry.get_cached_ranking("fast")) or FAST_PROVIDERS
            think_list = (await self.registry.get_cached_ranking("think")) or THINK_PROVIDERS
        else:
            fast_list = FAST_PROVIDERS
            think_list = THINK_PROVIDERS
            
        if profile.latency_budget <= 5 or profile.quality_target <= 7:
            preferred.extend([p for p in fast_list if p not in preferred])
        else:
            preferred.extend([p for p in think_list if p not in preferred])

        # Build chain: preferred first, then remaining in FALLBACK_CHAIN order
        seen = set(preferred)
        chain = list(preferred)
        for provider in FALLBACK_CHAIN:
            if provider not in seen:
                chain.append(provider)
                seen.add(provider)
        return chain

    # ── retry wrapper ─────────────────────────────────────────────────────

    async def _call_with_retries(
        self,
        provider: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Attempt a provider call with retries and exponential backoff.
        
        Raises:
            AIProviderError: If all retry attempts fail.
        """
        last_error: str = ""
        for attempt in range(_MAX_RETRIES + 1):  # 0, 1, 2 → 3 total attempts
            if attempt > 0:
                backoff = _RETRY_BACKOFF_BASE ** attempt
                logger.debug(
                    "Retrying %s (attempt %d/%d) after %.1fs backoff.",
                    provider, attempt + 1, _MAX_RETRIES + 1, backoff,
                )
                await asyncio.sleep(backoff)

            t0 = time.monotonic()
            try:
                text = await self._dispatch(
                    provider, prompt, system_prompt, temperature, max_tokens, force_model,
                )
                latency = time.monotonic() - t0
                self.stats[provider].record_success(latency)
                logger.info(
                    "✅ %s responded in %.2fs (attempt %d).",
                    provider, latency, attempt + 1,
                )
                return text
            except httpx.TimeoutException:
                last_error = f"Timeout after {_REQUEST_TIMEOUT}s"
                self.stats[provider].record_failure(last_error)
                logger.warning("%s attempt %d: %s", provider, attempt + 1, last_error)
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                self.stats[provider].record_failure(last_error)
                logger.warning("%s attempt %d: %s", provider, attempt + 1, last_error)
                # Don't retry on 4xx client errors (except 429 rate limit)
                if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                self.stats[provider].record_failure(last_error)
                logger.warning("%s attempt %d: %s", provider, attempt + 1, last_error)

        raise AIProviderError(provider, last_error)

    # ── synthesis routing ──────────────────────────────────────────────────

    async def call_deep(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1500,
    ) -> str:
        """Executes a multi-model synthesis pipeline for high-value offline tasks.
        
        Drafts via Ollama (or Cerebras/Groq) and G4F GPT-4o concurrently.
        Reviews and synthesizes the final output using Gemini 2.5 Pro.
        """
        logger.info("Initiating DEEP SYNTHESIS for prompt...")
        
        async def draft_fast():
            try:
                # Try ollama first, fallback to groq for local-like fast drafting
                return await self.call(task_type="fast", prompt=prompt, system_prompt=system_prompt, max_tokens=max_tokens)
            except Exception as e:
                logger.warning(f"Fast draft failed: {e}")
                return "(Failed to generate draft 1)"
                
        async def draft_g4f():
            try:
                return await self.call(task_type="think", prompt=prompt, system_prompt=system_prompt, force_provider="g4f_pro", max_tokens=max_tokens)
            except Exception as e:
                logger.warning(f"G4F draft failed: {e}")
                return "(Failed to generate draft 2)"
                
        # 1. Concurrent drafting
        draft1, draft2 = await asyncio.gather(draft_fast(), draft_g4f())
        
        # 2. Synthesis prompt
        synth_prompt = (
            f"You are the master synthesis reviewer. I have a task that requires absolute perfection.\n\n"
            f"=== ORIGINAL TASK ===\n{prompt}\n\n"
            f"=== DRAFT 1 (Fast/Local Model) ===\n{draft1}\n\n"
            f"=== DRAFT 2 (GPT-4o via G4F) ===\n{draft2}\n\n"
            f"Review both drafts. Synthesize their best insights, fix any logical flaws, "
            f"and produce the absolute best final response for the original task. "
            f"Do not mention the drafts in your response, just output the final synthesized version."
        )
        
        # 3. Final review via Gemini
        logger.info("Drafts complete. Calling Gemini for final review...")
        return await self.call(
            task_type="think", 
            prompt=synth_prompt, 
            system_prompt=system_prompt, 
            force_provider="gemini", 
            max_tokens=max_tokens
        )

    # ── dispatcher ────────────────────────────────────────────────────────

    async def _dispatch(
        self,
        provider: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Route to the correct provider-specific method."""
        if provider in _OPENAI_COMPATIBLE:
            return await self._call_openai_compatible(
                provider, prompt, system_prompt, temperature, max_tokens, force_model,
            )
        elif provider == "gemini":
            return await self._call_gemini(
                prompt, system_prompt, temperature, max_tokens, force_model,
            )
        elif provider == "cohere":
            return await self._call_cohere(
                prompt, system_prompt, temperature, max_tokens, force_model,
            )
        elif provider == "huggingface":
            return await self._call_huggingface(
                prompt, system_prompt, temperature, max_tokens, force_model,
            )
        elif provider.startswith("cf_") or provider == "cloudflare":
            return await self._call_cloudflare(
                provider, prompt, system_prompt, temperature, max_tokens, force_model,
            )
        elif provider == "ollama":
            return await self._call_ollama(
                prompt, system_prompt, temperature, max_tokens, force_model,
            )
        else:
            raise AIProviderError(provider, f"Unknown provider: {provider}")

    # ── OpenAI-compatible: groq, cerebras, openrouter ─────────────────────

    async def _call_openai_compatible(
        self,
        provider: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Call an OpenAI-compatible /chat/completions endpoint.
        Uses the ``openai`` async SDK for groq, cerebras, and openrouter.
        """
        cfg = AI_PROVIDERS[provider]
        api_key = get_api_key(provider)
        model = force_model if force_model else cfg["model"]

        if provider not in self._openai_clients:
            if provider in {"g4f", "g4f_pro", "gpt_5_5", "glm_5_2", "gpt_oss_120b"}:
                from g4f.client import ClientFactory
                self._openai_clients[provider] = ClientFactory.create_async_client("ollama.pro", api_key=api_key) if api_key else ClientFactory.create_async_client("ollama.pro")
            else:
                self._openai_clients[provider] = AsyncOpenAI(
                    api_key=api_key,
                    base_url=cfg["base_url"],
                    timeout=_REQUEST_TIMEOUT,
                    max_retries=0,  # We handle retries ourselves
                )

        client = self._openai_clients[provider]

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        extra_headers: dict[str, str] = {}
        if provider == "openrouter":
            extra_headers = {
                "HTTP-Referer": "https://sentinel.study",
                "X-Title": "SENTINEL",
            }

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers=extra_headers if extra_headers else None,
        )

        content = response.choices[0].message.content
        if not content:
            raise AIProviderError(provider, "Empty response content")

        return content.strip()

    # ── Google Gemini (REST) ──────────────────────────────────────────────

    async def _call_gemini(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Call the Google Gemini REST API via ``generateContent``.
        Docs: https://ai.google.dev/api/generate-content
        """
        cfg = AI_PROVIDERS["gemini"]
        api_key = get_api_key("gemini")
        model = force_model if force_model else cfg["model"]
        base = cfg["base_url"]
        url = f"{base}/models/{model}:generateContent?key={api_key}"

        body: dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]},
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }

        resp = await self._http.post(
            url,
            json=body,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise AIProviderError(
                "gemini",
                f"Unexpected response structure: {json.dumps(data)[:300]}",
            ) from exc

        if not text:
            raise AIProviderError("gemini", "Empty response text")

        return text.strip()

    # ── Cohere v2 /chat ───────────────────────────────────────────────────

    async def _call_cohere(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Call the Cohere v2 /chat endpoint.
        Docs: https://docs.cohere.com/reference/chat
        """
        cfg = AI_PROVIDERS["cohere"]
        api_key = get_api_key("cohere")
        model = force_model if force_model else cfg["model"]
        base = cfg["base_url"]
        url = f"{base}/chat"

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await self._http.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()

        data = resp.json()
        try:
            text = data["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "cohere",
                f"Unexpected response structure: {json.dumps(data)[:300]}",
            ) from exc

        if not text:
            raise AIProviderError("cohere", "Empty response text")

        return text.strip()

    # ── HuggingFace Inference API ─────────────────────────────────────────

    async def _call_huggingface(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Call the HuggingFace Inference API.
        Docs: https://huggingface.co/docs/api-inference/
        Uses the /v1/chat/completions OpenAI-compatible endpoint on HF.
        """
        cfg = AI_PROVIDERS["huggingface"]
        api_key = get_api_key("huggingface")
        model = force_model if force_model else cfg["model"]

        # HuggingFace exposes an OpenAI-compatible chat endpoint
        url = f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions"

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        resp = await self._http.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "huggingface",
                f"Unexpected response structure: {json.dumps(data)[:300]}",
            ) from exc

        if not text:
            raise AIProviderError("huggingface", "Empty response text")

        return text.strip()

    # ── Cloudflare Workers AI ─────────────────────────────────────────────

    async def _call_cloudflare(
        self,
        provider: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Call Cloudflare Workers AI.
        Requires CLOUDFLARE_ACCOUNT_ID env var in addition to the API key.
        Docs: https://developers.cloudflare.com/workers-ai/
        """
        import os
        cfg = AI_PROVIDERS[provider]
        api_key = get_api_key(provider)
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        model = force_model if force_model else cfg["model"]

        if not account_id:
            raise AIProviderError(provider, "CLOUDFLARE_ACCOUNT_ID not set")

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await self._http.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()

        data = resp.json()
        try:
            if "response" in data.get("result", {}):
                text = data["result"]["response"]
            elif "choices" in data.get("result", {}):
                text = data["result"]["choices"][0]["message"]["content"]
            else:
                raise ValueError("No response or choices in result")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise AIProviderError(
                provider,
                f"Unexpected response structure: {json.dumps(data)[:300]}",
            ) from exc

        if not text:
            raise AIProviderError(provider, "Empty response text")

        return text.strip()

    # ── Ollama Free API ───────────────────────────────────────────────────

    async def _call_ollama(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        force_model: str | None = None,
    ) -> str:
        """Call Ollama Free API."""
        cfg = AI_PROVIDERS["ollama"]
        model = force_model if force_model else cfg["model"]
        
        try:
            from ollamafreeapi import OllamaFreeAPI
        except ImportError:
            raise AIProviderError("ollama", "ollamafreeapi is not installed.")
            
        client = OllamaFreeAPI()
        
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"System: {system_prompt}\n\nUser: {prompt}"
            
        try:
            # We must wrap the synchronous generator in an async way,
            # or simply run it in an executor thread.
            def _sync_call():
                chunks = []
                for chunk in client.stream_chat(full_prompt, model=model):
                    chunks.append(chunk)
                return "".join(chunks)
                
            text = await asyncio.to_thread(_sync_call)
        except Exception as exc:
            raise AIProviderError("ollama", f"Ollama Free API Error: {exc}") from exc

        if not text:
            raise AIProviderError("ollama", "Empty response text")

        return text.strip()

    # ── stats / introspection ─────────────────────────────────────────────

    def get_stats_summary(self) -> dict[str, dict[str, Any]]:
        """Return a summary dict of provider stats for monitoring/logging."""
        summary: dict[str, dict[str, Any]] = {}
        for provider, stats in self.stats.items():
            has_key = bool(get_api_key(provider))
            summary[provider] = {
                "configured": has_key,
                "success_count": stats.success_count,
                "failure_count": stats.failure_count,
                "avg_latency_s": round(stats.avg_latency, 3),
                "last_error": stats.last_error or None,
            }
        return summary
