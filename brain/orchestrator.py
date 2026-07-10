"""
SENTINEL — Orchestrator (brain/orchestrator.py)

The single entry point for all requests. 
Receives a raw string and a reply callback. 
Manages conversation state, ContextBuilder, Brain invocation, and Action Compiler.
Follows the principle: "Every abstraction must pay rent."
"""

import logging
import json
from typing import Callable, Awaitable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

from sentinel.brain.study_blocks import StudyBlockEngine

logger = logging.getLogger("sentinel.brain.orchestrator")


def _state_supports(state, method_name: str) -> bool:
    return callable(getattr(type(state), method_name, None))

class Orchestrator:
    def __init__(
        self,
        state_db,
        context_builder,
        memory_engine,
        parser,
        action_planner,
        executor,
        reflection_engine,
        knowledge_engine,
        analyzer,
        notion_client,
        personal_memory=None,
        ai_engine=None,
    ):
        self.state = state_db
        self.context = context_builder
        self.memory = memory_engine
        self.parser = parser
        self.action_planner = action_planner
        self.executor = executor
        self.reflection_engine = reflection_engine
        self.knowledge_engine = knowledge_engine
        self.analyzer = analyzer
        self.notion = notion_client
        self.personal_memory = personal_memory
        self.ai = ai_engine

    async def handle(self, message: str, reply_callback: Callable[[str], Awaitable[None]], context_obj=None) -> None:
        """
        Main entry point. 
        message: The raw text from the user.
        reply_callback: An async function to send text back to the user interface.
        context_obj: Optional context (like telegram Update) needed for legacy executor until fully refactored.
        """
        text = message.strip()
        if not text:
            return

        state_key = await self.state.get_state("conversation_state")

        try:
            # 0. Onboarding state — takes priority over everything
            if state_key == "onboarding":
                from sentinel.brain.onboarding import OnboardingEngine
                onboarding = OnboardingEngine(self.state)
                response = await onboarding.handle_step(text)
                await reply_callback(response)
                return

            # 1. Handle explicit conversation states (state-machine)
            if state_key == "awaiting_block_report":
                await self._handle_block_report(text, reply_callback, context_obj)
                return
            elif state_key == "awaiting_done_block_selection":
                await self._handle_done_block_selection(text, reply_callback)
                return
            elif state_key == "awaiting_done_reflection":
                await self._handle_done_reflection(text, reply_callback)
                return
            elif state_key == "awaiting_homework":
                await self._handle_homework_input(text, reply_callback)
                return
            elif state_key == "awaiting_done_followup":
                await self._handle_done_followup(text, reply_callback, context_obj)
                return

            # 2. General Intent Parsing
            intent_data = await self.parser.classify_intent(text)
            
            # 3. Action Planner (The Brain)
            # This currently acts as the Intent -> Planner -> ExecutionPlan phase
            assistant_request = await self.action_planner.plan_actions(text, intent_data)
            
            # 4. Execute the sequence (The Runtime)
            if assistant_request.actions:
                success = await self.executor.execute_sequence(
                    assistant_request.actions, context_obj.get("update"), context_obj.get("context")
                )
                if success:
                    return

            # 5. Legacy Fallbacks (To be migrated fully to ActionCompiler later)
            intent = intent_data.intent
            if intent == "report":
                result = await self.parser.parse_performance_report(text)
                if result and result.attempted and result.time_taken:
                    await self.state.set_state("conversation_state", "confirming_report")
                    await self.state.set_state("pending_report", result.model_dump_json())
                    await self._send_confirmation(result, reply_callback)
                else:
                    await self._handle_general_message(text, intent_data, reply_callback)
            elif intent == "analyze_history":
                await self._handle_analyze_history(text, reply_callback)
            elif intent in ("query", "general"):
                await self._handle_general_message(text, intent_data, reply_callback)

        except Exception as e:
            logger.error(f"Orchestrator handling error: {e}", exc_info=True)
            await reply_callback("⚠️ An error occurred while processing your message.")

    # ── State Handlers (Moved from telegram_handler) ──

    async def _handle_block_report(self, text: str, reply, context_obj) -> None:
        if text.lower() in ("yes", "y", "confirm", "ok", "👍"):
            raw = await self.state.get_state("pending_report")
            if raw:
                from sentinel.bot.schemas import PerformanceReport
                report = PerformanceReport.model_validate_json(raw)
                await self._log_block_result(report, reply, context_obj)
                return

        result = await self.parser.parse_performance_report(text)
        if not result:
            await reply("🤔 Couldn't parse that. Try:\n• A=15 C=12 T=50\n• 15/12/50")
            return

        await self.state.set_state("pending_report", result.model_dump_json())
        await self.state.set_state("conversation_state", "confirming_report")
        await self._send_confirmation(result, reply)

    async def _send_confirmation(self, result, reply) -> None:
        subj = result.subject or "❓"
        ex = result.exercise_type or "❓"
        await reply(f"📋 Confirm this data:\n  Subject: {subj}\n  Exercise: {ex}\n  Attempted: {result.attempted}\n  Correct: {result.correct}\n  Time: {result.time_taken} min\n\nReply 'yes' to confirm.")

    async def _handle_homework_input(self, text: str, reply) -> None:
        parsed = await self.parser.parse_homework(text)
        if not parsed:
            await reply("⚠️ Couldn't parse homework. Try: Physics Ch.5 Ex2A Q1-20")
            return
            
        existing_raw = await self.state.get_state("homework_pending")
        existing = json.loads(existing_raw) if existing_raw else []
        existing.extend(hw.model_dump() if hasattr(hw, "model_dump") else dict(hw) for hw in parsed)
        await self.state.set_state("homework_pending", json.dumps(existing))
        await self.state.set_state("conversation_state", "default")
        
        summary = ["✅ Homework added:"]
        for hw in parsed:
            summary.append(f"  • {hw.subject}: {hw.exercise_type} ({hw.questions}Q)")
        await reply("\n".join(summary))

    async def _handle_done_block_selection(self, text: str, reply) -> None:
        today = datetime.now(_IST).strftime("%Y-%m-%d")
        block = None
        if _state_supports(self.state, "get_study_block_by_identifier"):
            block = await self.state.get_study_block_by_identifier(text.strip(), today)
        if not block:
            blocks = await self._planned_blocks(today)
            block = StudyBlockEngine.find_block(blocks, text.strip())
        if not block:
            await reply("Couldn't find that block. Reply with the number, label, or block_id from /done.")
            return
        if str(block.get("status", "")).upper() == "COMPLETED":
            await self.state.set_state("conversation_state", "default")
            await reply(f"{block.get('label') or block.get('block_label')} is already completed. Duplicate reflection ignored.")
            return

        await self.state.set_state("pending_done_block", json.dumps(block))
        await self.state.set_state("conversation_state", "awaiting_done_reflection")
        await reply(StudyBlockEngine.prompt_for_block(block))

    async def _handle_done_reflection(self, text: str, reply) -> None:
        raw_block = await self.state.get_state("pending_done_block")
        if not raw_block:
            await self.state.set_state("conversation_state", "default")
            await reply("Session expired. Please use /done again.")
            return

        block_data = json.loads(raw_block)
        unresolved = []
        if _state_supports(self.state, "get_unresolved_concepts"):
            unresolved = await self.state.get_unresolved_concepts(subject=block_data.get("subject"))
        history_context = [
            {
                "concept": c.get("concept_name"),
                "questions": c.get("linked_questions", []),
                "understanding": c.get("current_understanding", ""),
            }
            for c in unresolved[-5:]
        ] if unresolved else []

        parsed_response = await self.reflection_engine.process_block_reflection(block_data, history_context, text)
        if parsed_response.get("error"):
            await reply(f"Failed to parse report: {parsed_response['error']}")
            return
        if parsed_response.get("needs_followup") and parsed_response.get("followup_question"):
            await self.state.set_state("conversation_state", "awaiting_done_followup")
            await self.state.set_state("pending_done_data", json.dumps(parsed_response.get("parsed_data", {})))
            await self.state.set_state("pending_done_insight", parsed_response.get("historical_insight", ""))
            await reply(f"🤔 {parsed_response['followup_question']}")
            return

        await self._finalize_done_data(
            block_data,
            parsed_response.get("parsed_data", {}),
            parsed_response.get("historical_insight", ""),
            reply,
        )

    async def _handle_done_followup(self, text: str, reply, context_obj) -> None:
        state = self.state
        raw_data = await state.get_state("pending_done_data")
        if not raw_data:
            await state.set_state("conversation_state", "idle")
            await reply("Session expired. Please use /done again.")
            return
            
        parsed_data = json.loads(raw_data)
        parsed_data.setdefault("faculty_concepts", []).append(f"Follow-up answer: {text}")
        insight = await state.get_state("pending_done_insight") or ""
        
        await state.set_state("conversation_state", "idle")
        await state.set_state("pending_done_data", "")
        await state.set_state("pending_done_insight", "")
        
        raw_block = await state.get_state("pending_done_block")
        if not raw_block or not self.knowledge_engine:
            await reply("✅ Follow-up logged.")
            return

        block_data = json.loads(raw_block)
        await self._finalize_done_data(block_data, parsed_data, insight, reply)

    async def _planned_blocks(self, today: str) -> list[dict]:
        if _state_supports(self.state, "get_study_blocks"):
            blocks = await self.state.get_study_blocks(today)
            if blocks:
                return blocks
        raw_plan = await self.state.get_state("current_plan")
        if not raw_plan:
            return []
        try:
            from sentinel.brain.contracts import PlanningResult
            result = PlanningResult.model_validate_json(raw_plan)
            return [
                StudyBlockEngine.normalize_block(block, today, idx + 1).model_dump()
                for idx, block in enumerate(result.plan.blocks)
            ]
        except Exception:
            return []

    async def _finalize_done_data(self, block_data: dict, parsed_data: dict, insight: str, reply) -> None:
        result = await self.knowledge_engine.extract_assets(block_data, parsed_data)
        if result.get("error"):
            await reply(f"Error saving assets: {result['error']}")
            return

        from sentinel.notion_client.formulas import cognitive_yield

        today = datetime.now(_IST).strftime("%Y-%m-%d")
        attempted = parsed_data.get("attempted", 0)
        correct = parsed_data.get("correct", 0)
        time_taken = parsed_data.get("time_taken") or block_data.get("target_time", 0)
        actual_cy = cognitive_yield(
            T=time_taken,
            A=attempted,
            C=correct,
            exercise_type=block_data.get("exercise_type", "Ex 1A"),
            subject=block_data.get("subject", "Physics"),
        )
        block_data.update({
            "status": "COMPLETED",
            "attempted": attempted,
            "correct": correct,
            "T": time_taken,
            "A": attempted,
            "C": correct,
            "actual_cy": actual_cy,
        })
        if _state_supports(self.state, "complete_study_block") and block_data.get("block_id"):
            transition = await self.state.complete_study_block(block_data["block_id"], block_data)
            if transition.get("duplicate"):
                await self.state.set_state("conversation_state", "default")
                await reply(f"Duplicate reflection ignored: {block_data.get('label') or block_data.get('block_label')} is already completed.")
                return

        await self.state.save_completed_block(today, block_data)

        if self.notion:
            try:
                await self.notion.create_db1_row(
                    task_name=f"{block_data.get('label') or block_data.get('block_label', 'Block')}: {block_data.get('subject', 'Physics')} {block_data.get('exercise_type', 'Ex 1A')}",
                    subject=block_data.get("subject", "Physics"),
                    exercise_type=block_data.get("exercise_type", "Ex 1A"),
                    time_taken=time_taken,
                    attempted=attempted,
                    correct=correct,
                    block=block_data.get("block_label") or block_data.get("label", "Block"),
                    date_str=today,
                )
                await self.notion.update_db2_db3(
                    {
                        "attempted": attempted,
                        "correct": correct,
                        "subject": block_data.get("subject", "Physics"),
                        "exercise_type": block_data.get("exercise_type", "Ex 1A"),
                    },
                    assets=result.get("concept_assets", []),
                    conceptual_mistake=bool(result.get("concept_assets")),
                )
            except Exception:
                logger.warning("Failed to log finalized /done data to fake/real Notion", exc_info=True)

        idx_raw = await self.state.get_state("current_block_index")
        try:
            idx = int(idx_raw) if idx_raw else 0
        except (ValueError, TypeError):
            idx = 0

        await self.state.set_state("current_block_index", str(idx + 1))
        await self.state.set_state("pending_done_block", "")
        await self.state.set_state("conversation_state", "default")

        assets = result.get("concept_assets", [])
        asset_str = "\n".join([f"  • {a.get('concept_name')} (Needs Revision)" for a in assets])
        insight_msg = f"\n💡 {insight}\n" if insight else ""
        await reply(
            f"✅ Block Complete: {block_data.get('label') or block_data.get('block_label', 'Block')}\n"
            f"Stats: {correct}/{attempted} correct. CY: {actual_cy}\n{insight_msg}\n"
            f"Stored Concepts:\n{asset_str if assets else 'None detected.'}"
        )

    async def _handle_analyze_history(self, text: str, reply) -> None:
        text_lower = text.lower()
        is_weak_points_query = any(
            kw in text_lower for kw in [
                "weak", "weakness", "struggle", "bad at", "worst", "improve",
                "problem area", "where am i failing", "tell me my", "diagnose"
            ]
        )

        if is_weak_points_query:
            # Pull deep historical data — real numbers, not vibes
            await reply("📊 Pulling your full history... this is the real data.")
            try:
                data = await self.analyzer.get_weak_points_deep(months=6)
                from sentinel.brain.prompts import SYSTEM_PROMPT_COMPETITIVE_RIVAL
                prompt = (
                    f"The student asked: '{text}'\n\n"
                    f"Here is their REAL performance data from the last {data['period_months']} months "
                    f"({data['total_blocks_analyzed']} blocks analyzed):\n\n"
                    f"SUBJECT ACCURACY:\n{json.dumps(data['subject_accuracy'], indent=2)}\n\n"
                    f"WEAKEST EXERCISE TYPES (lowest accuracy):\n{json.dumps(data['weakest_exercise_types'], indent=2)}\n\n"
                    f"CHAPTERS WITH MOST ERRORS:\n{json.dumps(data['weakest_chapters'], indent=2)}\n\n"
                    f"RECURRING UNRESOLVED CONCEPTS:\n{json.dumps(data['recurring_unresolved_concepts'], indent=2)}\n\n"
                    f"Give a brutal, specific diagnosis. Name the exact chapters, exercise types, and concepts. "
                    f"Then give 3 concrete actions for the next 7 days. Use the data. No generic advice."
                )
                res = await self.analyzer.ai.call(
                    "general_chat", prompt,
                    system_prompt=SYSTEM_PROMPT_COMPETITIVE_RIVAL,
                    max_tokens=600
                )
                await reply(res)
            except Exception as e:
                logger.error("Weak points analysis failed: %s", e)
                await reply("⚠️ Failed to run deep analysis. Try again.")
            return

        # Default: 7-day trend
        trends = await self.analyzer.detect_trends(days=7)
        from sentinel.brain.prompts import ANALYZE_HISTORY_PROMPT
        prompt = ANALYZE_HISTORY_PROMPT.format(text=text, trends=json.dumps(trends, indent=2))
        try:
            res = await self.analyzer.ai.call("general_chat", prompt, max_tokens=400)
            await reply(res)
        except Exception:
            await reply("⚠️ Failed to analyze history.")




    async def _handle_general_message(self, text: str, intent_data, reply) -> None:
        """Unified AI handler. First checks for physics/math doubt — bans it. Then full context response."""
        if not self.ai:
            await reply("⚠️ AI engine not available.")
            return

        try:
            # ── STEP 0: Doubt Detection Gate ──────────────────────────────
            # If the student is trying to get SENTINEL to solve a concept/problem,
            # refuse immediately and log the doubt for faculty.
            from sentinel.brain.prompts import DOUBT_DETECTION_PROMPT
            try:
                doubt_check = await self.ai.call(
                    task_type="parser",
                    prompt=DOUBT_DETECTION_PROMPT.format(text=text),
                    system_prompt="Reply with exactly one word: YES or NO",
                    max_tokens=5,
                    temperature=0.0,
                )
                is_doubt = doubt_check.strip().upper().startswith("YES")
            except Exception:
                is_doubt = False  # Default to allowing if check fails

            if is_doubt:
                # Log the doubt to MongoDB as a faculty item
                try:
                    await self.state.upsert_concept_asset({
                        "concept_name": text[:120],
                        "subject": "Unknown",
                        "chapter": "Unknown",
                        "resolved": False,
                        "failure_type": "faculty_doubt",
                        "revisions": [],
                        "current_understanding": "Needs faculty clarification",
                        "linked_questions": [],
                    })
                except Exception:
                    pass
                await reply(
                    "❌ Not my job. Your faculty solves doubts.\n\n"
                    "📋 Logged to /faculty list. Ask your teacher next session.\n\n"
                    "Go back to work."
                )
                return

            # ── STEP 1: Load full context ──────────────────────────────────
            memory_context = {}
            if self.personal_memory:
                memory_context = await self.personal_memory.get_context_for_ai(text)

            raw_plan = await self.state.get_state("current_plan")
            plan_summary = "No plan generated yet."
            if raw_plan:
                try:
                    from sentinel.brain.contracts import PlanningResult
                    result = PlanningResult.model_validate_json(raw_plan)
                    blocks = result.plan.blocks
                    plan_summary = "\n".join(
                        f"  {b.block_label}: {b.subject} {b.exercise_type} ({b.question_count}Q, {b.target_time}m)"
                        for b in blocks
                    )
                except Exception:
                    plan_summary = "Plan exists but couldn't be parsed."

            from datetime import timedelta
            yesterday = (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_summary = await self.state.get_daily_summary(yesterday)

            unresolved = await self.state.get_unresolved_concepts()
            doubts_summary = ", ".join(
                c.get("concept_name", "?") for c in (unresolved or [])[:5]
            ) if unresolved else "None"

            profile = memory_context.get("student_profile", {})
            name = profile.get("name", "Student") if profile else "Student"
            faculty = profile.get("faculty", {})
            current_chapters = profile.get("current_chapters", {})
            rules = memory_context.get("study_rules", [])
            relevant_mems = memory_context.get("relevant_memories", [])
            now_str = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S %Z")

            context_str = (
                f"CURRENT DATE/TIME: {now_str}\n"
                f"STUDENT: {name}\n"
                f"FACULTY: {json.dumps(faculty)}\n"
                f"CURRENT CHAPTERS: {json.dumps(current_chapters)}\n\n"
                f"TODAY'S PLAN:\n{plan_summary}\n\n"
                f"YESTERDAY CY: {yesterday_summary.get('total_cy', 'N/A') if yesterday_summary else 'N/A'}\n\n"
                f"UNRESOLVED DOUBTS: {doubts_summary}\n\n"
                f"STUDY RULES: {json.dumps(rules) if rules else 'None'}\n\n"
                f"RELEVANT MEMORIES: {json.dumps(relevant_mems) if relevant_mems else 'None'}\n"
            )

            from sentinel.brain.prompts import SYSTEM_PROMPT_COMPETITIVE_RIVAL
            prompt = f"CONTEXT:\n{context_str}\nSTUDENT MESSAGE: {text}"

            response = await self.ai.call(
                task_type="general_chat",
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT_COMPETITIVE_RIVAL,
                max_tokens=400,
                temperature=0.5,
            )

            # Check if AI wants to save a memory rule
            if self.personal_memory and "SAVE_MEMORY:" in response:
                parts = response.split("SAVE_MEMORY:", 1)
                response_text = parts[0].strip()
                memory_text = parts[1].strip()
                if memory_text:
                    await self.personal_memory.save(memory_text)
                    response_text += "\n\n🧠 Saved to memory."
                response_text = response_text.encode("utf-16", "surrogatepass").decode("utf-16")
                await reply(response_text)
            else:
                response = response.strip().encode("utf-16", "surrogatepass").decode("utf-16")
                await reply(response)

        except Exception as e:
            logger.error("General message handler failed: %s", e, exc_info=True)
            await reply("⚠️ Couldn't process that right now. Try a command instead.")



    async def _log_block_result(self, report, reply, context_obj) -> None:
        from sentinel.notion_client.formulas import cognitive_yield
        from datetime import datetime
        
        A = report.attempted
        C = report.correct
        T = report.time_taken
        subject = report.subject or "Physics"
        ex_type = report.exercise_type or "Ex 1A"

        plan_raw = await self.state.get_state("current_plan")
        plan = {}
        blocks = []
        if plan_raw:
            try:
                from sentinel.brain.contracts import PlanningResult
                result = PlanningResult.model_validate_json(plan_raw)
                plan = result.plan.model_dump()
                blocks = plan.get("blocks", [])
            except Exception:
                plan = json.loads(plan_raw)
                plan_body = plan.get("plan", plan)
                blocks = plan_body.get("blocks", [])
        idx_raw = await self.state.get_state("current_block_index")
        idx = int(idx_raw) if idx_raw else 0
        current_block = blocks[idx] if idx < len(blocks) else {}

        if not report.subject and current_block.get("subject"):
            subject = current_block["subject"]
        if not report.exercise_type and current_block.get("exercise_type"):
            ex_type = current_block["exercise_type"]

        today = datetime.now(_IST).strftime("%Y-%m-%d")
        block_label = current_block.get("block_label", f"Block-{idx + 1}")
        cy = cognitive_yield(T, A, C, ex_type, subject)

        try:
            # We assume self.executor or a registry will eventually handle this.
            # But for now, we access notion directly if we injected it? Wait, orchestrator doesn't have self.notion.
            # I must pass self.notion into Orchestrator.
            if hasattr(self, "notion") and self.notion:
                task_name = f"{block_label}: {subject} {ex_type}"
                await self.notion.create_db1_row(
                    task_name=task_name, subject=subject, exercise_type=ex_type,
                    time_taken=T, attempted=A, correct=C, block=block_label, date_str=today
                )
                await self.notion.update_db2_db3(report)
        except Exception as e:
            logger.exception("Failed to log to Notion")

        block_entry = dict(current_block)
        block_entry.update({
            "status": "COMPLETED", "actual_cy": cy, "T": T, "A": A, "C": C,
            "subject": subject, "exercise_type": ex_type,
        })
        if _state_supports(self.state, "complete_study_block") and block_entry.get("block_id"):
            transition = await self.state.complete_study_block(block_entry["block_id"], block_entry)
            if transition.get("duplicate"):
                await reply(f"Duplicate reflection ignored: {block_label} is already completed.")
                return
        await self.state.save_completed_block(today, block_entry)
        
        await self.state.set_state("current_block_index", str(idx + 1))
        await self.state.set_state("conversation_state", "default")
        await self.state.set_state("pending_report", "")

        try:
            analysis = await self.analyzer.roaster.generate_block_roast(block_entry, plan) if hasattr(self.analyzer, 'roaster') else "✅ Logged."
            await reply(analysis)
        except Exception:
            await reply(f"✅ Logged. CY Earned: {cy}")
