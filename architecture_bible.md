# SENTINEL Architecture Bible

This document is the living roadmap and architectural constitution for SENTINEL. It combines the original design, the final decisions from the discussion, and the implementation plan in one continuous format.

SENTINEL is designed to evolve from a Telegram bot into a **fully-fledged AI operating system specialized for academic workflow management**.

---

## Table of Contents
1. [0. Design Principles](#0-design-principles)
2. [0.5. The Final Evolution (Architecture Diagram)](#05-the-final-evolution-architecture-diagram)
3. [Patterns We Reject](#patterns-we-reject)
4. [Non-goals](#non-goals)
5. [Core Data Contracts](#core-data-contracts)
6. [The Brain vs. Runtime Split & Public APIs](#the-brain-vs-runtime-split--public-apis)
7. [Component Architecture](#component-architecture)
   - [1. The Orchestrator](#1-the-orchestrator)
   - [2. System Context Builder & World State](#2-system-context-builder--world-state)
   - [3. Memory (Operational vs. Knowledge)](#3-memory-operational-vs-knowledge)
   - [4. Intent Engine & The Planner](#4-intent-engine--the-planner)
   - [5. Policy Engine & Constraints](#5-policy-engine--constraints)
   - [6. Action Compiler](#6-action-compiler)
   - [7. Tool Registry & Capability Discovery](#7-tool-registry--capability-discovery)
   - [8. Execution & Verification Engine](#8-execution--verification-engine)
8. [Cross-Cutting Components](#cross-cutting-components)
9. [Operating Modes](#operating-modes)
10. [Learning System (Pending)](#learning-system-pending)
11. [Implementation Status](#implementation-status)
12. [Implementation Plan](#implementation-plan)
13. [Reflection & Knowledge Capture](#reflection--knowledge-capture)
14. [Recovery Engine](#recovery-engine)
15. [Night Planning Engine](#night-planning-engine)
16. [Coaching Engine](#coaching-engine)
17. [DB Synchronization Strategy](#db-synchronization-strategy)
18. [Memory Strategy & Context Retrieval](#memory-strategy--context-retrieval)
19. [Morning Briefing](#morning-briefing)
20. [Weekly System Jobs](#weekly-system-jobs)
21. [Build Order](#build-order)
22. [Definition of Success](#definition-of-success)
23. [Final Principle](#final-principle)

---

## 0. Design Principles

- **LLMs never decide WHAT is allowed. LLMs decide WHAT is desirable. The Policy Engine decides WHAT is permitted.**
- **The ActionCompiler never calls an LLM.** Its job is purely translating an approved Execution Plan into concrete API/Tool calls deterministically.
- **WorldState is immutable.** The Planner receives a snapshot of the world. It cannot mutate it. Only Tools mutate reality.
- **Higher-trust sources override lower-trust sources.** (e.g. Notion/Mongo > User Message > LLM Output > AI Guess).
- **System confidence is explicit.** From Goal extraction to ActionResults, the system tracks its own confidence, not just LLM token probabilities.
- **Everything is versioned.** State objects and Plans enforce versioning to ensure stale actions never execute.
- LLMs never perform arithmetic.
- LLMs never directly modify databases or execute shell commands directly (must use a tool).
- Every state-changing action is auditable via an `AuditRecord`.
- **Don't add complexity until you need it.** The architecture describes the destination; the implementation follows the simplest path that supports today's features.
- **SENTINEL is an amplifier, not a replacement.** The protocol determines what should happen; SENTINEL preserves evidence, detects patterns, and improves the next day.

---

## 0.5. The Final Evolution (Architecture Diagram)

This is the north star. The Orchestrator sits above everything. The Context Builder prepares the environment, which is then passed to the **Brain** (which decides) and the **Runtime** (which performs). The AI System is **not** just the LLM.

```text
                 Telegram / Web / CLI
                         │
                         ▼
                   Orchestrator
                         │
                  Context Builder
                 (WorldState prep)
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
     Brain                           Runtime
        │                                 │
        │                                 │
  ┌─────┼─────────────┐          ┌─────────┼──────────┐
  ▼     ▼             ▼          ▼         ▼          ▼
Intent  Planner     Policy   ToolRegistry Executor EventBus
Engine    │           │            │          │         │
  └───────┴───────┬───┘            └──────────┴─────────┘
                  ▼
          Action Compiler
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   WorldState  Memory  Capability Registry
```

---

## Patterns We Reject

❌ **Giant prompts that do everything.**  
*Reason:* Impossible to maintain or version control.

❌ **AI directly editing Notion.**  
*Reason:* Must go through the `UpdateNotion` tool to enforce payload schema.

❌ **`os.system(user_input)`**  
*Reason:* Severe security and reproducibility risks.

❌ **Business logic inside prompts.**  
*Reason:* Business rules belong in Python (Policy Engine).

❌ **LLM chooses policy.**  
*Reason:* Policy should stay deterministic in Python. The LLM proposes, the Policy Engine decides.

❌ **MongoDB replacing the academic databases.**  
*Reason:* Mongo is the intelligence layer; Notion DB2 and DB3 remain the visible academic truth.

---

## Non-goals

SENTINEL is **NOT**:

- A general chatbot.
- A search engine.
- A coding IDE during Study Mode.
- A replacement for deterministic scheduling logic.
- A source of fabricated analytics.
- A live distraction machine during study blocks.

---

## Core Data Contracts

Everything in SENTINEL communicates using these strict, versioned objects:

- **`UserRequest`**: The raw incoming intent from the UI.
- **`WorldState`**: An immutable snapshot of reality (time, active block, CY deficit). Includes `version`.
- **`ContextBundle`**: The assembled package prepared by the Context Builder for consumption by the Brain/Runtime. Includes `version`.
- **`CapabilitySnapshot`**: The frozen state of available models and tools. Includes `version`.
- **`Goal`**: The explicit objective extracted by the Intent Engine. Includes `system_confidence`.
- **`CandidateExecutionPlan`**: The abstract roadmap proposed by the Planner. Not yet authorized. Includes `system_confidence`.
- **`ExecutionPlan`**: An authorized plan approved by the Policy Engine. Includes `version` and `system_confidence`.
- **`ToolCall`**: The concrete deterministic action emitted by the Action Compiler.
- **`ActionResult`**: The strict response from a Tool (success, reason, rollback_needed). Includes `system_confidence`.
- **`AuditRecord`**: The final logging object proving execution traceability.
- **`LearningEvent`**: The structured record created after a block or reflection.
- **`ErrorProfile`**: The long-term concept-level memory for repeated mistakes.
- **`TaskProfile`**: The task-level routing profile that controls model choice and synthesis rules.

*Flow: `UserRequest` → `ContextBundle` → `Goal` → `CandidateExecutionPlan` → `ExecutionPlan` → `ToolCall[]` → `ActionResult[]` → `AuditRecord` → `LearningEvent` / `ErrorProfile`*

---

## The Brain vs. Runtime Split & Public APIs

### The Brain (Decision Center)
Handles natural language understanding, capability discovery, and constraints evaluation. It outputs a verified `ExecutionPlan`.

**Public API:**
- `interpret(UserRequest, ContextBundle) -> Goal`
- `plan(Goal, ContextBundle) -> CandidateExecutionPlan`
- `evaluate(CandidateExecutionPlan) -> ExecutionPlan`
- `replan(RejectedPlan, Reason) -> CandidateExecutionPlan`

### The Runtime (Execution Center)
Knows nothing about natural language. It receives an `ExecutionPlan`, compiles it into concrete `ToolCalls`, executes them deterministically, and verifies the `ActionResult`.

**Public API:**
- `compile(ExecutionPlan) -> list[ToolCall]`
- `execute(list[ToolCall]) -> list[ActionResult]`
- `verify(ActionResult) -> bool`
- `rollback(Transaction)`

---

## Component Architecture

### 1. The Orchestrator

**Problem:** `telegram_handler.py` manages the workflow. Adding a Web UI means duplicating core logic.

**Industry:** A central Orchestrator manages the pipeline; UI layers are stateless "dumb pipes".

**SENTINEL:** `Orchestrator.handle(user_message)` manages the full lifecycle from User -> Context Builder -> Brain -> Runtime -> Reply.

**Implementation Notes:**
- The Orchestrator should own the request lifecycle.
- Telegram, web, and future interfaces must call the same core pipeline.
- The Orchestrator must not contain business rules that belong in the Policy Engine or Action Compiler.

---

### 2. System Context Builder & World State

**Problem:** Both Brain and Runtime need state (mode, permissions, schedule), causing duplicated queries.

**Industry:** A Context Builder runs at the top of the lifecycle, injecting a unified state package downward.

**SENTINEL:**
- **Context Builder:** Placed directly under the Orchestrator. Assembles the `ContextBundle` and `WorldState` so *everyone* consumes the exact same data.
- **WorldState:** Immutable snapshot containing current schedule, mode, provider health, constraints, today's CY, backlog pressure, active block, and current plan state.

**Implementation Notes:**
- The WorldState should never be mutated directly by the planner.
- State changes must happen only through tools and synchronized writes.
- The Context Builder should retrieve only relevant memory, not the full archive.

---

### 3. Memory (Operational vs. Knowledge)

**Problem:** "Memory" is currently treated as one monolith.

**Industry:** Separation of fast-changing state and slow-changing knowledge.

**SENTINEL:**
- **Operational Memory:** Today's schedule, pending confirmations, running jobs (Fast-changing).
- **Knowledge Memory:** Benchmarks, Notion schema, provider history, concept evolution, faculty notes, error profiles, learning patterns (Slow-changing).

**Implementation Notes:**
- Operational Memory should stay small and recent.
- Knowledge Memory should store meaning, not raw clutter.
- MongoDB is the intelligence layer, not the full academic truth.

---

### 4. Intent Engine & The Planner

**Problem:** Planners do too much (understanding intent + generating concrete schedules). "Reasoner" implies endless Chain-of-Thought loops.

**Industry:** Separate natural language interpretation (Goal Extraction) from operational planning.

**SENTINEL:**
- **Intent Engine:** "The user wants to postpone revision because the exam went badly." (Outputs an explicit `Goal` object with confidence).
- **Planner:** Receives the `Goal` and outputs a `CandidateExecutionPlan` (versioned).

**Implementation Notes:**
- The Intent Engine should extract meaning, not create the schedule.
- The Planner should propose a strategy, not directly mutate reality.
- The user’s protocol already defines sequence and thresholds; the planner optimizes around them.
- Do not force long prompts or high-friction interaction.

---

### 5. Policy Engine & Constraints

**Problem:** LLMs hallucinate plans violating fixed constraints.

**Industry:** Deterministic engines evaluate proposed actions against hard rules.

**SENTINEL:** `PolicyEngine` evaluates the `CandidateExecutionPlan`. If approved, it is cast to an `ExecutionPlan`. Violations force a `replan()`.

**Implementation Notes:**
- Policy must remain deterministic in Python.
- The Policy Engine should enforce:
  - hard stop
  - no impossible overloads
  - no schedule overlap
  - no hidden reduction in mandatory work
  - no destructive automation without permission
- If a plan fails policy, the system should explain why and propose the nearest feasible alternative.

---

### 6. Action Compiler

**Problem:** Planners emit low-level executable actions, mixing abstraction layers.

**Industry:** Action Compilers translate high-level plans into concrete API calls deterministically.

**SENTINEL:** Using strict Python logic (zero LLMs), the compiler translates an authorized `ExecutionPlan` into concrete `ToolCalls`.

**Implementation Notes:**
- The Action Compiler never calls an LLM.
- It translates approved goals into tool calls such as:
  - update Notion
  - write reflection asset
  - update error profile
  - schedule follow-up
  - sync weekly analysis
- If the plan is too vague to compile, the Planner must improve it.

---

### 7. Tool Registry & Capability Discovery

**Problem:** The system assumes tools and providers are always available.

**Industry:** A Registry exposes real-time availability of providers, models, tools, and rate limits.

**SENTINEL:** `CapabilityRegistry` exposes health. `ToolRegistry` exposes typed inputs/outputs.

*Note: A **Service** (e.g., `MongoService`) handles connections and retries. A **Tool** (e.g., `MongoQueryTool`) is what the ActionCompiler invokes.*

**Implementation Notes:**
- Capability discovery should include:
  - model availability
  - provider latency
  - provider health
  - tool availability
  - task-specific suitability
- The router should use measured behavior, not just hardcoded preference.

---

### 8. Execution & Verification Engine

**Problem:** What happens if Action 1 succeeds but Action 2 fails?

**Industry:** Strict Execution loop with Verification and Transaction Boundaries.

**SENTINEL:** `ActionExecutor` processes tools. It establishes **Transaction Boundaries** (BEGIN -> Run Tools -> VERIFY -> COMMIT or ROLLBACK). If a tool fails, the pipeline halts or rolls back based on the `ActionResult`.

**Implementation Notes:**
- Separate execution from verification.
- Every meaningful tool call should produce an `ActionResult`.
- Failures should not be hidden.
- When rollback is impossible, the system should emit a clear audit trail.

---

## Cross-Cutting Components

- **Observability (Audit):** A strict `AuditRecord` tracking timestamp, user_message, intent, retrieved_memory, provider, tools_called, policy_result, and success.
- **Event Bus:** Instead of tight coupling, everything emits events (`ActionFailed`, `ScheduleChanged`). The Scheduler, Metrics, and Notifications subscribe to the Bus.
- **Task Queue:** Background work (Weekly roast, Notion sync, health checks, nightly planning) goes into a queue rather than direct execution by the scheduler.
- **Logging & Metrics:** Structured JSON logging, latency tracking, success/failure tracking, and sync visibility.
- **Synchronization Engine:** Keeps Notion DB2, Notion DB3, and Mongo aligned.

---

## Operating Modes

SENTINEL operates in different modes. Tools are gated by the current mode.

| Tool         | Study | Dev | Maintenance | Read-Only |
| ------------ | ----- | --- | ----------- | --------- |
| Notion       | ✅     | ✅   | ✅           | ✅ (Read) |
| Mongo        | ✅     | ✅   | ✅           | ✅ (Read) |
| Git          | ❌     | ✅   | ❌           | ❌        |
| Terminal     | ❌     | ✅   | ⚠️          | ❌        |
| File Editing | ❌     | ✅   | ❌           | ❌        |
| Benchmarks   | ❌     | ✅   | ✅           | ❌        |

*Mode changes are executed via `/mode <type>` and evaluated by the Orchestrator before hitting the Tool Registry.*

---

## Learning System (Pending)

Data helps SENTINEL improve by turning past behavior into future routing, guidance, and scheduling decisions. Instead of guessing from scratch, the system asks: *"For this type of task, what worked best in the past?"*

The system will learn through three **Memory Layers**:

1. **Raw Events:** User message, provider used, latency, result success/failure, subject, task type, time of day.
2. **Summaries:** Short periodic reports (e.g., best provider for weekly analysis this month, weakest subject this week).
3. **Decision Memory:** The actual routing brain that sets rules based on the summaries.

**Implementation Strategy:**
Start with a `memory_profiles` collection in MongoDB. Every time SENTINEL finishes a task, it updates this record. Over time, the router stops being a guesser and becomes a learner.

Example `memory_profiles` document:
```json
{
  "task": "weekly_analysis",
  "best_provider": "gemini",
  "best_model": "gemini-2.5-pro",
  "avg_latency": 8.2,
  "success_rate": 0.97,
  "json_validity": 0.99,
  "last_updated": "..."
}
```

*Note: The model will NOT learn by rewriting its own prompts randomly. It will strictly learn through MongoDB records, task summaries, provider stats, and routing rules.*

---

## Implementation Status

This section tracks the live evolution of SENTINEL against this architectural blueprint.

### ✅ Completed (Foundation & Brain)
- **Architecture Constitution**: Defined Brain vs Runtime, data contracts, and strict design principles.
- **Provider Matrix**: Configured tiered AI models (Gemini Pro, GPT-4o, DeepSeek, local fallback).
- **TaskProfile Routing**: Deprecated static task tiers. Routing is now driven by `TaskProfile` definitions containing latency budgets, quality targets, and background capabilities.
- **Deep Synthesis (`call_deep`)**: Created a multi-model consensus pipeline (Ollama + GPT-4o -> Gemini Pro review) strictly for non-time-bounded, high-value background tasks.
- **Background Intelligence Benchmarking (`CapabilityRegistry`)**: Built the subsystem to asynchronously test model latency, sort them by speed/health, and cache rankings in MongoDB. Interactive tasks now enjoy zero-latency routing lookups.
- **Intent Engine & Parsers**: Structured natural language into typed `pydantic` schemas with AI fallback on regex failure.
- **Reflection Engine**: Extracts root-cause bottlenecks from study blocks.
- **Knowledge Engine**: Converts reflections into structured knowledge assets.
- **Planning Engine**: Runs the nightly optimization committee.
- **Coaching Engine**: Runs weekly macro-analysis and habit diagnosis.

### 🔄 In Progress (Runtime Layer)
- **The Orchestrator**: Decoupling execution pipeline from `telegram_handler.py`.
- **Synchronization Engine**: Ensuring DB2, DB3, and Mongo stay aligned.

### ⏳ Pending (The Missing Links)
- **Tool Registry**: Formalizing tools into a discoverable registry with strict input/output schemas.
- **Action Compiler**: Deterministic compiler to translate `ExecutionPlan` into concrete `ToolCalls`.
- **Policy Engine**: Intercepting `CandidateExecutionPlan` to validate actions against fixed system constraints (e.g. "Don't schedule blocks past 01:00 AM").
- **Execution & Verification Engine**: Executing `ToolCalls` with transaction boundaries and implementing a rollback/undo mechanism.
- **Context Builder & World State**: Injecting immutable states (time, CY deficit, schedule) into a unified package before the Brain operates.
- **Learning System**: Storing task history, provider success rates, and user study patterns to dynamically adjust `TaskProfiles`.

---

# 12. Implementation Plan

## 12.1 Implementation Philosophy

SENTINEL is an amplifier, not a replacement.

- The JEE protocol remains the deterministic source of truth for sequence, timing, and thresholds.
- SENTINEL adds value by preserving evidence, extracting meaning from study blocks, surfacing patterns, and preparing tomorrow better than today.
- Do not build features that add friction during the study block itself.
- Keep the student-facing interaction short: one block start, one block end, one nightly planning pass, one weekly review pass.
- The database must remain a diagnostic ledger plus intelligence layer, never a noisy real-time supervisor.

## 12.2 What SENTINEL Must Actually Do

SENTINEL’s job is limited to five useful outcomes:

1. Preserve what happened today.
2. Convert raw block output into structured academic evidence.
3. Help answer “what should change tomorrow?”
4. Keep Notion DB2 and DB3 synced with the real learning state.
5. Build a long-term model of what concepts, habits, and task patterns repeatedly hurt progress.

Anything outside that scope is optional later work.

---

## 13. Reflection & Knowledge Capture

## 13.1 Reflection Interview

After each block, SENTINEL should capture only the missing information.

The interaction should be short and adaptive:

- attempted
- correct
- skipped
- reason skipped
- doubts
- time-bounded questions
- current understanding
- what will be asked to faculty
- what remains unresolved

### Example flow
User:
> 18 attempted, 15 correct, don't understand Q7,8, got time bounded in Q10,11.

SENTINEL:
- summarizes what it understood
- asks only for missing concept-level detail if needed
- stores a structured learning event
- updates DB2, DB3, and Mongo together

## 13.2 Knowledge Engine Output

The Knowledge Engine should not just record “Q5 wrong.”
It should record knowledge density:

- subject
- chapter
- concept
- failure type
- faculty explanation
- current understanding
- revision date
- resolved status

It should also classify mistake types such as:

- concept
- formula
- calculation
- reading
- visualization
- silly mistake
- time pressure

## 13.3 QuestionAsset

The most useful long-term object is not a homework row.
It is a `QuestionAsset`.

A `QuestionAsset` should hold:

- question_id
- subject
- chapter
- source
- difficulty
- attempts
- correct
- last_attempt
- concepts
- doubts
- faculty_notes
- resolved
- revision_dates

This lets SENTINEL remember *how you understand*, not just *what you submitted*.

---

## 14. Recovery Engine

## 14.1 Purpose

The Recovery Engine finds productive fallback work when a block ends early, when you are fatigued, or when a task is impossible to finish in time.

## 14.2 Inputs

- free time available
- current fatigue / overload signal
- skipped questions
- unanswered doubts
- unfinished homework
- revision backlog
- recent weak concepts
- next coaching / doubt class timing

## 14.3 Output

The Recovery Engine should recommend the best small productive action, for example:

- finish the leftover questions from yesterday
- do a short revision of a weak concept
- prepare a faculty question summary
- reattempt an already-started question set
- switch to lower-friction revision if the current block is mentally heavy

## 14.4 Priority Rule

The Recovery Engine should always prefer:

1. unfinished work already started
2. near-term backlog that is easiest to rescue
3. concepts tied to repeated errors
4. confidence-building revision
5. new work only when the above are empty

---

## 15. Night Planning Engine

## 15.1 Purpose

The Night Planning Engine is the main optimization pass of SENTINEL.
It turns tomorrow’s rough Notion list into a realistic next-day mission plan.

## 15.2 Inputs

- tomorrow’s Notion tasks
- current revision backlog
- current precision tracker / error log
- today’s learning events
- coaching schedule
- fixed commitments
- recent weak concepts
- recent fatigue / time pressure patterns
- available study time for tomorrow

## 15.3 Output

The output should be:

- a realistic battle plan for tomorrow
- a top 3 mission list
- backlog adjustments
- a list of high-risk items
- a note on what must move if time is insufficient

## 15.4 Behavior

The engine should:

- preserve the protocol’s sequencing logic
- reject impossible overloads
- move lower-priority work when needed
- use the strongest models only for high-value planning jobs
- produce a short morning briefing

## 15.5 Deep Analysis

For nightly planning, it is acceptable to use expensive model synthesis because this runs off the critical study path.

This is where multi-model analysis can be used to:

- critique the user’s draft plan
- compare it against backlog and weak points
- check whether the time distribution is realistic
- produce the morning briefing

## 15.6 Rule of 3

Every morning, SENTINEL should hide the full chaos and provide exactly three highest-value actions:

1. one theory task
2. one homework task
3. one revision task

This is the visible interface on top of a much larger internal plan.

---

## 16. Coaching Engine

## 16.1 Purpose

The Coaching Engine runs weekly and looks for the single most damaging habit or pattern across roughly 30 days.

## 16.2 Questions It Should Answer

- What habit is causing the most damage?
- Which subject or concept is still leaking marks repeatedly?
- Where is time getting wasted the most?
- Which kind of mistake is not improving over time?
- What macro change will improve next week the most?

## 16.3 Output

It should produce:

- the damaging habit
- the harsh truth
- the macro adjustment for next week

## 16.4 Role in the System

The coaching output should feed the next week’s planning, but it should not directly rewrite the day-to-day protocol.

It is a strategic review layer, not the study executor.

---

## 17. DB Synchronization Strategy

## 17.1 Notion DB2

Revision backlog should remain the visible revision queue.

It answers:
- what should be revised
- when it should be revised
- what priority it has
- what the revision status is

## 17.2 Notion DB3

Precision tracker / error log should remain the visible record of mistakes, conceptual gaps, and faculty-level unresolved items.

It answers:
- what went wrong
- what concept failed
- whether faculty is needed
- whether the item is repeated

## 17.3 MongoDB

Mongo should store:
- learning patterns
- memory summaries
- concept evolution
- provider metrics
- routing history
- reflection history
- task profiles
- cached analysis results

## 17.4 Synchronization Engine

The Synchronization Engine keeps DB2, DB3, and Mongo aligned.

- DB3 stores the evidence of the error.
- DB2 stores the revision action needed.
- Mongo stores the long-term evolution of that concept.

No database should silently drift from the others.

---

## 18. Memory Strategy & Context Retrieval

## 18.1 What Mongo Should Remember

Mongo should remember the long-term learning history, not raw textbook content.
It should focus on:
- how you struggle
- which concepts repeat
- which interventions helped
- which tasks work best at what time
- which providers/models work best for which task types

## 18.2 What Mongo Should Not Do

Mongo should not become a duplicate of Notion.

It should not replace the current revision queue or error tracker.

It should not be the only place where the current state exists.

## 18.3 Context Retrieval

Before any important AI call, the system should retrieve only the relevant memories, not the whole archive.

Relevant retrieval examples:
- all unresolved doubts for the current chapter
- repeated mistakes for the current concept
- recent failure reasons
- weekly or monthly pattern summaries
- provider performance for the current task type

---

## 19. Morning Briefing

## 19.1 Purpose

Every morning SENTINEL should give a short battle plan.

## 19.2 Should Include

- today’s top 3 tasks
- time risk
- backlog risk
- one critical concept to watch
- one faculty follow-up item if needed
- a short motivating message

## 19.3 Should Exclude

- giant paragraphs
- unnecessary model reasoning
- raw database dumps
- long generic advice

---

## 20. Weekly System Jobs

## 20.1 Coaching Schedule Sync

If enabled, SENTINEL can sync coaching schedule on a scheduled day.

This should remain behind a dedicated tool and permission gate.

## 20.2 Weekly Macro Review

Once per week, SENTINEL should summarize:
- how the week went
- the main habit causing damage
- which concepts are becoming persistent weak points
- what should shift in the next week

## 20.3 Optional Automation Safety

Any background automation must be deliberate, visible, and bounded by clear scope.

---

## 21. Build Order

## Phase 1 — Core Loop
- Orchestrator
- Context Builder
- Reflection Engine
- Knowledge Engine
- DB2/DB3 sync
- Learning Event model

## Phase 2 — Planning
- Night Planning Engine
- Morning Briefing
- Recovery Engine
- Rule of 3 implementation

## Phase 3 — Weekly Intelligence
- Coaching Engine
- Error Intelligence System
- long-term learning summaries
- synchronization engine

## Phase 4 — Refinement
- provider ranking cache
- capability snapshots
- improved retrieval
- better faculty-question summaries
- concept graph / error story evolution

---

## 22. Definition of Success

SENTINEL is successful if:

- you lose less knowledge between blocks
- you waste less time on the same mistake
- you ask teachers more precise questions
- backlog becomes visible instead of vague
- tomorrow’s plan becomes more realistic than today’s
- the system helps you study with less friction and more honesty
- every block leaves behind structured progress, not just effort

---

## 23. Final Principle

SENTINEL should not try to be smart in the abstract.

It should be useful in the exact moments you are stuck, tired, behind, confused, or overloaded.

If a feature does not help preserve learning, reduce confusion, protect time, or improve tomorrow’s plan, it should not be built yet.

---

## Appendix A. Final Summary of the Product

SENTINEL is an academic operating system that:

- captures study block outcomes,
- extracts doubts and learning assets,
- synchronizes Notion and Mongo,
- builds better plans at night,
- gives the top 3 actions in the morning,
- tracks recurring weak concepts across months,
- and quietly turns today’s mistakes into tomorrow’s advantage.

The protocol decides what must happen.
SENTINEL ensures nothing is lost and nothing is forgotten.
