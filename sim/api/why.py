from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.db.models import Action, AgentState, Memory, System1Decision


def build_why_chain(session: Session, run_id: UUID, agent_id: UUID, sweep: int) -> dict:
    """Assemble why-chain from stored rows only (no new LLM call)."""
    decisions = list(
        session.scalars(
            select(System1Decision).where(
                System1Decision.run_id == run_id,
                System1Decision.agent_id == agent_id,
                System1Decision.sweep == sweep,
            )
        )
    )
    memories = list(
        session.scalars(
            select(Memory).where(
                Memory.run_id == run_id,
                Memory.agent_id == agent_id,
                Memory.sweep == sweep,
            )
        )
    )
    actions = list(
        session.scalars(
            select(Action).where(
                Action.run_id == run_id,
                Action.agent_id == agent_id,
                Action.sweep == sweep,
            )
        )
    )
    state = session.get(AgentState, {"run_id": run_id, "agent_id": agent_id, "sweep": sweep})
    return {
        "run_id": str(run_id),
        "agent_id": str(agent_id),
        "sweep": sweep,
        "inputs_and_system1": [
            {
                "input_ref": d.input_ref,
                "route": d.route,
                "escalated_by": d.escalated_by,
                "answers": d.answers,
            }
            for d in decisions
        ],
        "memories": [
            {"id": str(m.id), "type": m.type, "content": m.content, "importance": m.importance}
            for m in memories
        ],
        "actions": [
            {
                "id": str(a.id),
                "type": a.type,
                "intent_text": a.intent_text,
                "outcome": a.outcome,
            }
            for a in actions
        ],
        "state": {
            "slow": state.slow if state else None,
            "fast": state.fast if state else None,
            "policy_stances": state.policy_stances if state else None,
        },
    }
