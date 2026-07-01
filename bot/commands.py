"""
SENTINEL — Telegram Command Handlers (bot/commands.py)
All /command handlers for the Telegram bot.  Each handler accesses
shared services (planner, analyzer, roaster, parser, notion, state_db)
via ``context.bot_data``.
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')
from telegram import Update
from telegram.ext import ContextTypes
from sentinel.brain.contracts import PlanningResult, ExecutionPlan
from sentinel.brain.morning_formatter import MorningFormatter
from sentinel.brain.study_blocks import StudyBlockEngine
from sentinel.config import (
    BOT_NAME,
    DAILY_CY_TARGET,
    SUBJECTS,
    TELEGRAM_CHAT_ID,
    TIMEZONE,
)
logger = logging.getLogger("sentinel.commands")
# ── Helpers to pull services from context ──────────────────────────────────
def _planner(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data["planner"]
def _analyzer(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data["analyzer"]
def _roaster(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data["roaster"]
def _parser(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data["parser"]
def _notion(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data["notion"]
def _state(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data["state_db"]
def _scheduler(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.bot_data.get("scheduler")
async def _reply(update: Update, text: str) -> None:
    """Send a reply, truncating if necessary for Telegram's 4096-char limit."""
    max_len = 4000
    if len(text) > max_len:
        text = text[:max_len] + "\n\n… (truncated)"
    await update.message.reply_text(text)

def _state_supports(state, method_name: str) -> bool:
    return callable(getattr(type(state), method_name, None))

async def _planned_blocks_for_today(state, plan=None) -> list[dict]:
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    if _state_supports(state, "get_study_blocks"):
        blocks = await state.get_study_blocks(today)
        if blocks:
            return blocks

    if plan is None:
        raw_plan = await state.get_state("current_plan")
        if not raw_plan:
            return []
        plan = PlanningResult.model_validate_json(raw_plan).plan

    return [
        StudyBlockEngine.normalize_block(block, today, idx + 1).model_dump()
        for idx, block in enumerate(plan.blocks)
    ]

async def _resolve_done_block(state, selector: str, plan=None) -> dict | None:
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    if _state_supports(state, "get_study_block_by_identifier"):
        block = await state.get_study_block_by_identifier(selector, today)
        if block:
            return block
    blocks = await _planned_blocks_for_today(state, plan)
    return StudyBlockEngine.find_block(blocks, selector)

async def _current_planned_block(state, plan) -> dict | None:
    idx_raw = await state.get_state("current_block_index")
    try:
        idx = int(idx_raw) if idx_raw else 0
    except (ValueError, TypeError):
        idx = 0
    blocks = await _planned_blocks_for_today(state, plan)
    if idx >= len(blocks):
        return None
    return blocks[idx]

def _split_done_selector(args: str) -> tuple[str | None, str]:
    stripped = args.strip()
    if not stripped:
        return None, ""
    parts = stripped.split(None, 1)
    candidate = parts[0]
    if candidate.isdigit() or candidate.upper().startswith(("EB", "RB", "TA", "ADV", "AB")) or re.match(r"\d{4}-\d{2}-\d{2}-", candidate):
        return candidate, parts[1] if len(parts) > 1 else ""
    return None, stripped

async def _prompt_done_block_selection(update: Update, state, plan=None) -> None:
    blocks = await _planned_blocks_for_today(state, plan)
    if not blocks:
        await _reply(update, "No planned blocks found. Generate a plan first with /plan.")
        return
    lines = ["Which block?"]
    for idx, block in enumerate(blocks, 1):
        lines.append(StudyBlockEngine.describe_block(block, idx))
    lines.append("\nReply with the number, label, or block_id.")
    await state.set_state("conversation_state", "awaiting_done_block_selection")
    await _reply(update, "\n".join(lines))
# ── /start ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message + register chat_id. Triggers onboarding if first run."""
    chat_id = str(update.effective_chat.id)
    state = _state(context)
    await state.set_state("chat_id", chat_id)
    logger.info("Registered chat_id: %s", chat_id)

    # Check if onboarding is needed
    from sentinel.brain.onboarding import OnboardingEngine
    onboarding = OnboardingEngine(state)
    if not await onboarding.is_onboarded():
        first_question = await onboarding.get_first_question()
        await _reply(update, first_question)
        return

    # Already onboarded — show welcome
    profile = await state.get_student_profile()
    name = profile.get("name", "Soldier") if profile else "Soldier"
    await _reply(update, (
        f"⚔️ {BOT_NAME} ONLINE\n"
        f"{'━' * 24}\n"
        f"Welcome back, {name}.\n\n"
        f"Target: IIT Bombay CS.\n"
        f"Daily CY target: {DAILY_CY_TARGET}.\n\n"
        f"Commands: /help\n"
        f"Let's get to work. 🔥"
    ))
# ── /plan ───────────────────────────────────────────────────────────────────
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the current day plan, or generate a new one."""
    state = _state(context)
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    plan_date = await state.get_state("plan_date")
    if plan_date == today:
        raw = await state.get_state("current_plan")
        if raw:
            result = PlanningResult.model_validate_json(raw)
            msg = MorningFormatter().format_morning_briefing(result.plan)
            await _reply(update, msg)
            return
    # Generate a new plan
    await _reply(update, "⏳ Generating today's plan…")
    coaching_days_raw = await state.get_state("coaching_days")
    coaching_days = json.loads(coaching_days_raw) if coaching_days_raw else []
    weekday = datetime.now(_IST).strftime("%A")[:3]
    day_type = "coaching" if weekday in coaching_days else "self_study"
    homework_raw = await state.get_state("homework_pending")
    homework = json.loads(homework_raw) if homework_raw else []
    try:
        result = await _planner(context).generate_daily_plan(day_type, coaching_days, homework)
        msg = MorningFormatter().format_morning_briefing(result.plan)
        await _reply(update, msg)
    except Exception:
        logger.exception("Plan generation failed")
        await _reply(update, "❌ Plan generation failed. Try again later.")
# ── /status ─────────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show daily CY progress so far."""
    state = _state(context)
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    raw = await state.get_state("current_plan")
    if not raw:
        await _reply(update, "📭 No plan found for today. Use /plan first.")
        return
    _result = PlanningResult.model_validate_json(raw)
    plan = _result.plan
    # Fetch today's completed blocks
    completed = await state.get_today_blocks(today)
    earned_cy = sum(b.get("actual_cy", 0) for b in completed)
    total_planned = getattr(plan, "total_expected_cy", DAILY_CY_TARGET)
    blocks_done = len(completed)
    blocks_total = len(plan.blocks)
    pct = (earned_cy / total_planned * 100) if total_planned > 0 else 0
    # Progress bar (10 segments)
    filled = int(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    lines = [
        f"📊 STATUS — {today}",
        f"{'━' * 24}",
        f"CY: {earned_cy}/{total_planned} ({pct:.0f}%)",
        f"[{bar}]",
        f"Blocks: {blocks_done}/{blocks_total} completed",
    ]
    # Per-subject breakdown from completed blocks
    subject_cy: dict[str, int] = {}
    for b in completed:
        subj = b.get("subject", "?")
        subject_cy[subj] = subject_cy.get(subj, 0) + b.get("actual_cy", 0)
    if subject_cy:
        lines.append("")
        for subj in SUBJECTS:
            cy_val = subject_cy.get(subj, 0)
            lines.append(f"  {subj}: CY={cy_val}")
    # Current block info
    current_idx_raw = await state.get_state("current_block_index")
    if current_idx_raw is not None:
        try:
           for idx in range(blocks_total):
               if idx < len(completed):
                   b = completed[idx]
                   lines.append(f"✅ {b.get('block_label', '?')} — {b.get('actual_cy', 0)} CY earned")
               elif idx == int(current_idx_raw):
                   cur = plan.blocks[idx]
                   lines.extend([
                       "",
                       f"▶️ Current: {cur.block_label} — {cur.subject} {cur.exercise_type}",
                   ])
        except (ValueError, TypeError):
            pass
    await _reply(update, "\n".join(lines))
# ── /homework ───────────────────────────────────────────────────────────────
async def cmd_homework(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log coaching homework."""
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        await _reply(update, (
            "📝 Usage: /homework <details>\n"
            "Example: /homework Physics Ch.5 Ex2A Q1-20, Chem Ch.3 MLE Q1-15"
        ))
        return
    text = args[1]
    parsed = await _parser(context).parse_homework(text)
    if not parsed:
        await _reply(update, "⚠️ Couldn't parse homework. Try: Physics Ch.5 Ex2A Q1-20")
        return
    # Save to state
    state = _state(context)
    existing_raw = await state.get_state("homework_pending")
    existing = json.loads(existing_raw) if existing_raw else []
    parsed_entries = [hw.model_dump() if hasattr(hw, "model_dump") else dict(hw) for hw in parsed]
    existing.extend(parsed_entries)
    await state.set_state("homework_pending", json.dumps(existing))
    summary_lines = ["✅ Homework logged:"]
    for hw in parsed:
        summary_lines.append(
            f"  • {hw.subject}: {hw.chapter or '?'} {hw.exercise_type} "
            f"({hw.questions}Q)"
        )
    summary_lines.append(f"\nTotal pending: {len(existing)} items")
    await _reply(update, "\n".join(summary_lines))
# ── /week ───────────────────────────────────────────────────────────────────
async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set coaching days for the week."""
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        state = _state(context)
        current = await state.get_state("coaching_days")
        days = json.loads(current) if current else []
        if days:
            await _reply(update, f"📅 Current coaching days: {', '.join(days)}\nTo change: /week Mon Wed Fri")
        else:
            await _reply(update, "📅 No coaching days set.\nUsage: /week Mon Wed Fri")
        return
    days = await _parser(context).parse_week_schedule(args[1])
    if not days:
        await _reply(update, "⚠️ Couldn't parse days. Try: /week Mon Wed Fri")
        return
    await _state(context).set_state("coaching_days", json.dumps(days))
    await _reply(update, f"✅ Coaching days set: {', '.join(days)}")
# ── /skip ───────────────────────────────────────────────────────────────────
async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Skip the current block (with accountability log)."""
    state = _state(context)
    raw = await state.get_state("current_plan")
    if not raw:
        await _reply(update, "📭 No active plan. Nothing to skip.")
        return
    _result = PlanningResult.model_validate_json(raw)
    plan = _result.plan
    idx_raw = await state.get_state("current_block_index")
    try:
        idx = int(idx_raw) if idx_raw else 0
    except (ValueError, TypeError):
        idx = 0
    blocks = plan.blocks
    if idx >= len(blocks):
        await _reply(update, "✅ All blocks completed. Nothing to skip.")
        return
    skipped = blocks[idx]
    reason = ""
    parts = update.message.text.split(None, 1)
    if len(parts) > 1:
        reason = parts[1]
    # Log skip to Notion DB4
    try:
        await _notion(context).create_db4_row(
            action_type="block_skip",
            decision=f"Skipped {skipped.block_label}",
            reasoning=reason or "No reason given",
            data_snapshot=skipped.model_dump_json(),
        )
    except Exception:
        logger.warning("Failed to log skip to DB4", exc_info=True)
    skipped_entry = skipped.model_dump()
    skipped_entry["status"] = "SKIPPED"
    skipped_entry["actual_cy"] = 0
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    if _state_supports(state, "skip_study_block") and skipped_entry.get("block_id"):
        await state.skip_study_block(skipped_entry["block_id"], reason)
    await state.save_completed_block(today, skipped_entry)
    # Track skipped count
    skipped_count_raw = await state.get_state("blocks_skipped_today")
    skipped_count = int(skipped_count_raw) if skipped_count_raw else 0
    await state.set_state("blocks_skipped_today", str(skipped_count + 1))
    # Advance to next block
    await state.set_state("current_block_index", str(idx + 1))
    await _reply(update, (
        f"⏭️ Skipped: {skipped.block_label} — {skipped.subject} {skipped.exercise_type}\n"
        f"Reason: {reason or 'none given'}\n\n"
        f"Skipping doesn't erase the deficit. Yesterday-you wouldn't skip. 😤"
    ))
    # Notify scheduler to move to next block
    scheduler = _scheduler(context)
    if scheduler and idx + 1 < len(blocks):
        try:
            await scheduler.cancel_block_jobs()
            # The scheduler will pick up the next block automatically
        except Exception:
            logger.warning("Failed to update scheduler after skip", exc_info=True)
# ── /sick ───────────────────────────────────────────────────────────────────
async def cmd_sick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate off-day protocol."""
    state = _state(context)
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    await state.set_state("day_type", "off_day")
    await state.set_state(f"off_day_{today}", "true")
    # Log to DB4
    try:
        await _notion(context).create_db4_row(
            action_type="off_day",
            decision=f"Off day activated for {today}",
            reasoning="User reported sick/off",
            data_snapshot=json.dumps({"date": today}),
        )
    except Exception:
        logger.warning("Failed to log off-day to DB4", exc_info=True)
    # Cancel today's scheduled blocks
    scheduler = _scheduler(context)
    if scheduler:
        try:
            await scheduler.cancel_block_jobs()
        except Exception:
            logger.warning("Failed to cancel scheduled blocks", exc_info=True)
    await _reply(update, (
        f"😴 Off-day protocol activated for {today}.\n\n"
        f"All remaining blocks cancelled.\n"
        f"Rest up. Tomorrow, we go harder.\n\n"
        f"(If you feel better later, use /plan to re-generate.)"
    ))
# ── /sync ───────────────────────────────────────────────────────────────────
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Force Notion data sync."""
    await _reply(update, "🔄 Syncing with Notion…")
    try:
        stats = await _notion(context).get_daily_stats(datetime.now(_IST).strftime("%Y-%m-%d"))
        await _reply(update, f"✅ Sync complete.\n\nToday's Notion stats:\n{json.dumps(stats, indent=2)}")
    except Exception:
        logger.exception("Notion sync failed")
        await _reply(update, "❌ Notion sync failed. Check API health with /status.")
# ── /scores ─────────────────────────────────────────────────────────────────
async def cmd_scores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log coaching test scores and trigger recalibration."""
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        await _reply(update, (
            "📝 Usage: /scores <results>\n"
            "Example: /scores Physics 45/120, Chem 62/120, Maths 55/120"
        ))
        return
    parsed_scores = await _parser(context).parse_test_scores(args[1])
    scores = parsed_scores.model_dump() if hasattr(parsed_scores, "model_dump") else dict(parsed_scores)
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    scores["date"] = today
    # Extract optional notes
    notes = ""
    text_lower = args[1].lower()
    if "note" in text_lower or "notes" in text_lower:
        note_match = args[1].split("note", 1)
        if len(note_match) > 1:
            notes = note_match[1].strip().lstrip("s:").strip()
    scores["notes"] = notes
    # Save to state_db
    try:
        await _state(context).save_test_score(
            test_date=today,
            p_score=scores["p_score"], p_total=scores["p_total"],
            c_score=scores["c_score"], c_total=scores["c_total"],
            m_score=scores["m_score"], m_total=scores["m_total"],
            notes=notes,
        )
    except Exception:
        logger.exception("Failed to save test scores")
        await _reply(update, "❌ Failed to save scores.")
        return
    total = scores["p_score"] + scores["c_score"] + scores["m_score"]
    max_total = scores["p_total"] + scores["c_total"] + scores["m_total"]
    pct = (total / max_total * 100) if max_total else 0
    await _reply(update, (
        f"📝 Test scores saved — {today}\n"
        f"{'━' * 24}\n"
        f"Physics: {scores['p_score']}/{scores['p_total']}\n"
        f"Chem: {scores['c_score']}/{scores['c_total']}\n"
        f"Maths: {scores['m_score']}/{scores['m_total']}\n"
        f"Total: {total}/{max_total} ({pct:.0f}%)\n\n"
        f"⏳ Generating recalibration analysis…"
    ))
    # Generate recalibration
    try:
        recal = await _roaster(context).generate_test_recalibration(scores)
        await _reply(update, recal)
    except Exception:
        logger.exception("Recalibration failed")
        await _reply(update, "⚠️ Recalibration analysis failed.")
# ── /roast ──────────────────────────────────────────────────────────────────
async def cmd_roast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """On-demand performance roast."""
    await _reply(update, "🔥 Preparing your roast…")
    today = datetime.now(_IST)
    from datetime import timedelta
    # Find the start of the current week (Monday)
    # Find the start of the current week (Monday)
    weekday_offset = today.weekday()  # 0 = Monday
    week_start = (today - timedelta(days=weekday_offset)).strftime("%Y-%m-%d")
    week_end = today.strftime("%Y-%m-%d")
    try:
        roast = await _roaster(context).generate_weekly_roast(week_start, week_end)
        await _reply(update, roast)
    except Exception:
        logger.exception("Roast generation failed")
        await _reply(update, "❌ Roast failed. Even the AI is disappointed in you.")
# ── /done (Adaptive Reflection Interview) ──────────────────────────────────
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a single block-end brain-dump."""
    parts = update.message.text.split(None, 1)
    state = _state(context)
    raw_plan = await state.get_state("current_plan")
    
    if not raw_plan:
        await _reply(update, "No active plan found. I need to know what block you just finished.")
        return
        
    _result = PlanningResult.model_validate_json(raw_plan)
    plan = _result.plan

    if len(parts) < 2 or not parts[1].strip():
        await _prompt_done_block_selection(update, state, plan)
        return

    selector, user_message = _split_done_selector(parts[1])
    if selector:
        selected_block = await _resolve_done_block(state, selector, plan)
        if not selected_block:
            await _reply(update, f"Could not find planned block '{selector}'. Use /done to see today's blocks.")
            return
        if not user_message:
            await state.set_state("conversation_state", "awaiting_done_reflection")
            await state.set_state("pending_done_block", json.dumps(selected_block))
            await _reply(update, StudyBlockEngine.prompt_for_block(selected_block))
            return
        current_block_data = selected_block
    else:
        current_block_data = await _current_planned_block(state, plan)

    if not current_block_data:
        await _reply(update, "You've finished all blocks for today!")
        return
    
    await _reply(update, "🧠 Analyzing your report...")
    
    # Pass to Reflection Engine
    reflection_engine = context.bot_data.get("reflection_engine")
    if not reflection_engine:
        await _reply(update, "System error: Reflection Engine not wired.")
        return
        
    # Fetch historical context for this subject
    unresolved = await state.get_unresolved_concepts(subject=current_block_data.get("subject"))
    history_context = [
        {"concept": c.get("concept_name"), "questions": c.get("linked_questions", []), "understanding": c.get("current_understanding", "")} 
        for c in unresolved[-5:]  # Give recent 5 concepts
    ] if unresolved else []
    
    parsed_response = await reflection_engine.process_block_reflection(current_block_data, history_context, user_message)
    
    if parsed_response.get("error"):
        await _reply(update, f"Failed to parse report: {parsed_response['error']}")
        return
        
    if parsed_response.get("needs_followup") and parsed_response.get("followup_question"):
        # Save state to continue interview
        await state.set_state("conversation_state", "awaiting_done_followup")
        await state.set_state("pending_done_data", json.dumps(parsed_response.get("parsed_data", {})))
        await state.set_state("pending_done_insight", parsed_response.get("historical_insight", ""))
        await state.set_state("pending_done_block", json.dumps(current_block_data))
        await _reply(update, f"🤔 {parsed_response['followup_question']}")
        return
        
    # We have all data, pass to Knowledge Engine
    await _finalize_done_report(update, context, current_block_data, parsed_response.get("parsed_data", {}), parsed_response.get("historical_insight", ""))

async def _finalize_done_report(update: Update, context: ContextTypes.DEFAULT_TYPE, current_block, parsed_data: dict, historical_insight: str = "") -> None:
    state = _state(context)
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    
    # 1. Compute CY and Save to DB First (Deterministic)
    from sentinel.notion_client.formulas import cognitive_yield
    attempted = parsed_data.get("attempted", 0)
    correct = parsed_data.get("correct", 0)
    time_taken = parsed_data.get("time_taken") or current_block.get("target_time", 0)
    actual_cy = cognitive_yield(
        T=time_taken, A=attempted, C=correct,
        exercise_type=current_block.get("exercise_type", "Ex 1A"),
        subject=current_block.get("subject", "Physics"),
    )
    
    block_data = dict(current_block)
    block_data.update({
        "status": "COMPLETED",
        "attempted": attempted, "correct": correct,
        "T": time_taken, "A": attempted, "C": correct,
        "actual_cy": actual_cy,
    })
    
    if _state_supports(state, "complete_study_block") and block_data.get("block_id"):
        transition = await state.complete_study_block(block_data["block_id"], block_data)
        if transition.get("duplicate"):
            await _reply(update, f"Duplicate reflection ignored: {block_data.get('label') or block_data.get('block_label')} is already completed.")
            return
            
    await state.save_completed_block(today, block_data)
    
    # 2. Extract Assets (Best Effort Background AI)
    knowledge_engine = context.bot_data.get("knowledge_engine")
    assets = []
    if knowledge_engine:
        await _reply(update, "📦 Packing knowledge assets into permanent memory...")
        result = await knowledge_engine.extract_assets(current_block, parsed_data)
        if result.get("error"):
            await _reply(update, f"⚠️ Error extracting assets (block saved anyway): {result['error']}")
        else:
            assets = result.get("concept_assets", [])
    
    # 3. Update Notion
    notion = context.bot_data.get("notion")
    if notion:
        try:
            await notion.create_db1_row(
                task_name=f"{current_block.get('block_label', 'Block')}: {current_block.get('subject', 'Physics')} {current_block.get('exercise_type', 'Ex 1A')}",
                subject=current_block.get("subject", "Physics"),
                exercise_type=current_block.get("exercise_type", "Ex 1A"),
                time_taken=time_taken, attempted=attempted, correct=correct,
                block=current_block.get("block_label", "Block"), date_str=today,
            )
            await notion.update_db2_db3(
                {
                    "attempted": attempted,
                    "correct": correct,
                    "subject": current_block.get("subject", "Physics"),
                    "exercise_type": current_block.get("exercise_type", "Ex 1A"),
                },
                assets=assets,
                conceptual_mistake=bool(assets),
            )
        except Exception:
            logger.warning("Failed to log /done result to Notion", exc_info=True)
    
    # 4. Move to next block
    raw_plan = await state.get_state("current_plan")
    _result = PlanningResult.model_validate_json(raw_plan)
    plan = _result.plan
    idx_raw = await state.get_state("current_block_index")
    try:
        idx = int(idx_raw) if idx_raw else 0
    except (ValueError, TypeError):
        idx = 0
        
    await state.set_state("current_block_index", str(idx + 1))
    
    # Notify scheduler
    scheduler = _scheduler(context)
    if scheduler:
        try:
            await scheduler.cancel_block_jobs()
        except Exception:
            pass
            
    # Format reply
    asset_str = "\n".join([f"  • {a.get('concept_name')} (Needs Revision)" for a in assets])
    insight_msg = f"\n💡 {historical_insight}\n" if historical_insight else ""
    msg = (
        f"✅ Block Complete: {current_block.get('block_label', 'Block')}\n"
        f"Stats: {correct}/{attempted} correct. CY: {actual_cy}\n{insight_msg}\n"
        f"Stored Concepts:\n{asset_str if assets else 'None detected.'}\n\n"
        f"Use /doubts to see your unresolved items."
    )
    
    await state.set_state("conversation_state", "default")
    await _reply(update, msg)

# ── /doubts (Faculty Formatter) ─────────────────────────────────────────────
async def cmd_doubts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Format unresolved concepts for faculty."""
    state = _state(context)
    parts = update.message.text.split(None, 1)
    subject = parts[1].strip() if len(parts) > 1 else None
    
    unresolved = await state.get_unresolved_concepts(subject=subject)
    
    if not unresolved:
        await _reply(update, f"No unresolved doubts{' for ' + subject if subject else ''}! You're clear.")
        return
        
    lines = [f"🧑‍🏫 FACULTY DOUBTS {'— ' + subject if subject else ''}\n"]
    for i, concept in enumerate(unresolved, 1):
        lines.append(f"{i}. Concept: {concept.get('concept_name')}")
        lines.append(f"   Context: {concept.get('subject')} - {concept.get('chapter')}")
        lines.append(f"   Questions: {', '.join(concept.get('linked_questions', []))}")
        lines.append(f"   My Understanding: {concept.get('current_understanding', 'Unknown')}")
        lines.append("")
        
    await _reply(update, "\n".join(lines))

# ── /jee ────────────────────────────────────────────────────────────────────
async def cmd_jee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """JEE countdown and reality check."""
    state = _state(context)
    profile = await state.get_student_profile()

    from datetime import date
    today = date.today()

    if profile:
        main_date = date.fromisoformat(profile.get("jee_main_date", "2028-01-20"))
        adv_date = date.fromisoformat(profile.get("jee_advanced_date", "2028-06-01"))
    else:
        main_date = date(2028, 1, 20)
        adv_date = date(2028, 6, 1)

    days_main = (main_date - today).days
    days_adv = (adv_date - today).days

    # Get streak
    streak = await state.get_streak("daily_target")
    streak_count = streak.get("current_count", 0) if streak else 0

    # Get latest test
    latest_test = await state.get_latest_test_score()
    test_line = "No test scores yet."
    if latest_test:
        test_line = (
            f"Physics {latest_test.get('p_score', 0)}/{latest_test.get('p_total', 120)} | "
            f"Chem {latest_test.get('c_score', 0)}/{latest_test.get('c_total', 120)} | "
            f"Maths {latest_test.get('m_score', 0)}/{latest_test.get('m_total', 120)}"
        )

    # Get unresolved concepts count
    unresolved = await state.get_unresolved_concepts()
    doubts_count = len(unresolved) if unresolved else 0

    lines = [
        f"⏰ JEE COUNTDOWN",
        f"{'━' * 24}",
        f"JEE Main:     {days_main} days",
        f"JEE Advanced: {days_adv} days",
        f"",
        f"🔥 Streak: {streak_count} days",
        f"📝 Last test: {test_line}",
        f"❓ Unresolved doubts: {doubts_count}",
    ]
    await _reply(update, "\n".join(lines))

# ── /backlog ────────────────────────────────────────────────────────────────
async def cmd_backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all pending work: homework, doubts, revision."""
    state = _state(context)

    # Homework pending
    hw_raw = await state.get_state("homework_pending")
    homework = json.loads(hw_raw) if hw_raw else []

    # Unresolved concepts by subject
    unresolved = await state.get_unresolved_concepts()
    subj_counts = {}
    for c in (unresolved or []):
        s = c.get("subject", "Other")
        subj_counts[s] = subj_counts.get(s, 0) + 1

    lines = [
        f"📋 BACKLOG",
        f"{'━' * 24}",
        f"Homework pending: {len(homework)} items",
    ]
    for hw in homework[:5]:
        subj = hw.get("subject", "?")
        ex = hw.get("exercise_type", "?")
        ch = hw.get("chapter", "")
        lines.append(f"  • {subj} {ch} {ex}")
    if len(homework) > 5:
        lines.append(f"  ... and {len(homework) - 5} more")

    lines.append(f"")
    lines.append(f"Unresolved doubts: {len(unresolved or [])}")
    for subj, count in sorted(subj_counts.items()):
        lines.append(f"  {subj}: {count}")

    await _reply(update, "\n".join(lines))

# ── /faculty ────────────────────────────────────────────────────────────────
async def cmd_faculty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show doubt list for a specific teacher or subject."""
    state = _state(context)
    parts = update.message.text.split(None, 1)
    query = parts[1].strip() if len(parts) > 1 else None

    # Resolve query to a subject using memory system
    subject = None
    faculty_name = query
    if query:
        memory = context.bot_data.get("personal_memory")
        if memory:
            subject = await memory.resolve_subject(query)
        if not subject:
            # Check if query is itself a subject name
            for s in SUBJECTS:
                if query.lower() in s.lower() or s.lower() in query.lower():
                    subject = s
                    break

    if not subject and not query:
        # No argument — show all unresolved
        profile = await state.get_student_profile()
        faculty = profile.get("faculty", {}) if profile else {}
        lines = [f"🧑‍🏫 FACULTY DOUBT LIST\n"]
        for subj in SUBJECTS:
            teacher = faculty.get(subj, "")
            unresolved = await state.get_unresolved_concepts(subject=subj)
            if unresolved:
                header = f"{subj}" + (f" ({teacher})" if teacher else "")
                lines.append(f"▸ {header}: {len(unresolved)} doubts")
                for c in unresolved[:3]:
                    lines.append(f"  • {c.get('concept_name', '?')}")
                if len(unresolved) > 3:
                    lines.append(f"  ... +{len(unresolved) - 3} more")
                lines.append("")
        if len(lines) == 1:
            lines.append("No unresolved doubts! You're clear.")
        await _reply(update, "\n".join(lines))
        return

    if not subject:
        await _reply(update, f"Couldn't resolve '{query}' to a subject. Try /faculty Physics or /faculty <teacher name>.")
        return

    unresolved = await state.get_unresolved_concepts(subject=subject)
    if not unresolved:
        await _reply(update, f"No unresolved doubts for {subject}! 🎯")
        return

    lines = [f"🧑‍🏫 DOUBTS FOR {faculty_name or subject}" + (f" ({subject})" if faculty_name and faculty_name != subject else ""), ""]
    for i, concept in enumerate(unresolved, 1):
        lines.append(f"{i}. {concept.get('concept_name', '?')}")
        chapter = concept.get('chapter', '')
        if chapter:
            lines.append(f"   Chapter: {chapter}")
        questions = concept.get('linked_questions', [])
        if questions:
            lines.append(f"   Questions: {', '.join(questions[:5])}")
        understanding = concept.get('current_understanding', '')
        if understanding:
            lines.append(f"   My understanding: {understanding}")
        lines.append("")

    lines.append("Show this on your phone when you walk into class. 📱")
    await _reply(update, "\n".join(lines))

# ── /remember ───────────────────────────────────────────────────────────────
async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save something to personal memory."""
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        await _reply(update, "Usage: /remember <something to remember>\nExample: /remember Shantanu sir is my chemistry teacher")
        return
    memory = context.bot_data.get("personal_memory")
    if not memory:
        await _reply(update, "⚠️ Memory system not available.")
        return
    result = await memory.save(args[1])
    summary = result.get("summary", args[1])
    rtype = result.get("resolved_type", "fact")
    await _reply(update, f"🧠 Noted ({rtype}): {summary}")

# ── /feedback ───────────────────────────────────────────────────────────────
async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture feedback about the bot's last response."""
    state = _state(context)
    args = update.message.text.split(None, 1)

    if len(args) < 2:
        await _reply(update, "Usage: /feedback <what went wrong>\nExample: /feedback it listed physics doubts but I asked for chemistry")
        return

    feedback_text = args[1]
    # Get recent chat history for context
    recent = await state.get_recent_chat_history(limit=4)
    conv_state = await state.get_state("conversation_state")

    await state.save_feedback({
        "feedback_text": feedback_text,
        "recent_conversation": recent,
        "conversation_state": conv_state,
        "resolved": False,
    })
    await _reply(update, "📝 Feedback saved. This helps me improve. Thanks.")

# ── /help ───────────────────────────────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all available commands."""
    await _reply(update, (
        f"⚔️ {BOT_NAME} COMMANDS\n"
        f"{'━' * 24}\n\n"
        f"📋 /plan — Show or generate daily plan\n"
        f"📊 /status — CY progress today\n"
        f"✅ /done <report> — Finish block and reflect\n"
        f"🧑‍🏫 /doubts [subject] — Show unresolved concepts\n"
        f"🧑‍🏫 /faculty [name] — Doubt list for coaching\n"
        f"📋 /backlog — All pending work\n"
        f"⏰ /jee — JEE countdown\n"
        f"📝 /homework <details> — Log homework\n"
        f"📅 /week <days> — Set coaching days\n"
        f"⏭️ /skip [reason] — Skip current block\n"
        f"😴 /sick — Activate off-day\n"
        f"🔄 /sync — Force Notion sync\n"
        f"📝 /scores <results> — Log test scores\n"
        f"🔥 /roast — On-demand roast\n"
        f"🧠 /remember <fact> — Save to memory\n"
        f"📝 /feedback <text> — Report an issue\n"
        f"❓ /help — This message"
    ))

# ── /mode ───────────────────────────────────────────────────────────────────
async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle system mode between developer and study."""
    args = " ".join(context.args) if context.args else ""
    bot_ref = context.bot_data.get("bot_ref")
    if bot_ref:
        await bot_ref._handle_mode(update, context, args)
    else:
        await _reply(update, "⚠️ Mode switching unavailable.")

COMMANDS = [
    cmd_start,
    cmd_plan,
    cmd_status,
    cmd_homework,
    cmd_week,
    cmd_skip,
    cmd_sick,
    cmd_sync,
    cmd_scores,
    cmd_roast,
    cmd_done,
    cmd_doubts,
    cmd_jee,
    cmd_backlog,
    cmd_faculty,
    cmd_remember,
    cmd_feedback,
    cmd_help,
    cmd_mode,
]
