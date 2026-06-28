# ADR 001: Separation of Brain and Runtime via Orchestrator

**Date:** 2026-06-26  
**Status:** Accepted  

## Context
SENTINEL began as a standard Telegram bot where `telegram_handler.py` managed parsing, planning, and execution in a single monolithic flow. As the system expanded to include deterministic constraint evaluation, tool execution, and multiple AI providers, the coupling between the Telegram UI and the execution logic made the system fragile and hard to test.

## Decision
We will separate the system into three distinct layers:
1. **The Interface Layer (Telegram, Web, CLI):** Stateless "dumb pipes" that only receive inputs and display outputs.
2. **The Brain:** Responsible for reasoning, planning, memory retrieval, and policy evaluation. Generates an `ExecutionPlan`.
3. **The Runtime:** Responsible for deterministic tool execution, verification, and event broadcasting. 

This will be managed by a central **Orchestrator** which handles the lifecycle of a `UserRequest` through these systems.

## Reason
- **Modularity:** UI logic (Telegram) should not know how to evaluate a constraint against a Notion schedule.
- **Testability:** An `Orchestrator` can be tested purely via Python objects (`UserRequest`) without needing a mocked Telegram connection.
- **Safety:** By explicitly separating the Brain from the Runtime, we enforce the rule that the ActionCompiler and Tool Executors never call an LLM, reducing the risk of hallucinated destructive actions.

## Pros
- Allows easy addition of a Discord bot or Web UI later.
- Creates clear transaction boundaries for execution.
- Enables the Policy Engine to cleanly intercept and reject plans before any code touches the Runtime.

## Cons
- Introduces more boilerplate (Data Contracts like `UserRequest`, `Goal`, `ExecutionPlan`).
- Refactoring `telegram_handler.py` will require migrating existing working logic.
