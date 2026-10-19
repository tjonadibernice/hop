"""The curator agent as a LangGraph state machine.

    START -> agent -> tools ----+      (look something up, then think again)
               ^  -> submit ---+--> END (decision recorded)
               |  -> nudge ----+      (answered in prose: ask once for a tool call)
               +--------------+   -> END when the turn limit or a second
                                         prose answer stops it

The graph only gathers evidence and a proposal. It never writes to the
database; curator/service.py applies the proposal through the guardrails.
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from app.curator.model import AgentModel
from app.curator.tools import CuratorToolbox, SubmitDecision

NUDGE = "Use one of the tools, or call submit_decision with your decision."
TOOL_RESULT_CHARS = 500  # kept per step in the audit trail


class CuratorState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    turns: int  # model calls so far
    tool_calls: int  # lookups so far (submit_decision doesn't count)
    nudged: bool
    proposal: SubmitDecision | None
    stop_reason: str | None
    provider: str | None
    steps: list[dict[str, Any]]  # the audit trail


def initial_state(messages: list[AnyMessage]) -> CuratorState:
    return CuratorState(
        messages=messages,
        turns=0,
        tool_calls=0,
        nudged=False,
        proposal=None,
        stop_reason=None,
        provider=None,
        steps=[],
    )


def _last_ai(state: CuratorState) -> AIMessage:
    message = state["messages"][-1]
    assert isinstance(message, AIMessage)
    return message


def build_graph(
    model: AgentModel, toolbox: CuratorToolbox, *, max_turns: int, max_tool_calls: int
):
    async def agent(state: CuratorState) -> dict:
        if state["turns"] >= max_turns:
            return {"stop_reason": f"turn limit ({max_turns}) reached"}
        message, provider = await model.invoke(state["messages"])
        return {
            "messages": [message],
            "turns": state["turns"] + 1,
            "provider": provider,
        }

    def after_agent(state: CuratorState) -> str:
        if state["stop_reason"]:
            return END
        calls = _last_ai(state).tool_calls
        if any(call["name"] == "submit_decision" for call in calls):
            return "submit"
        if calls:
            return "tools"
        return "give_up" if state["nudged"] else "nudge"

    async def tools(state: CuratorState) -> dict:
        used = state["tool_calls"]
        steps = list(state["steps"])
        replies = []
        for call in _last_ai(state).tool_calls:
            if used >= max_tool_calls:
                content = "Tool limit reached. Call submit_decision now."
            else:
                content = await toolbox.call(call["name"], call["args"])
                used += 1
                steps.append(
                    {
                        "tool": call["name"],
                        "args": call["args"],
                        "result": content[:TOOL_RESULT_CHARS],
                    }
                )
            replies.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": replies, "tool_calls": used, "steps": steps}

    def submit(state: CuratorState) -> dict:
        calls = _last_ai(state).tool_calls
        decision = next(call for call in calls if call["name"] == "submit_decision")
        # Every tool call needs an answer before the model can speak again
        others = [
            ToolMessage(
                content="Not run: submit_decision was called in the same turn.",
                tool_call_id=call["id"],
            )
            for call in calls
            if call is not decision
        ]
        try:
            proposal = SubmitDecision.model_validate(decision["args"])
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}"
                for e in error.errors()
            )
            reply = ToolMessage(
                content=f"Invalid decision ({problems}). Call submit_decision again.",
                tool_call_id=decision["id"],
            )
            return {"messages": [reply, *others]}
        steps = [
            *state["steps"],
            {"tool": "submit_decision", "args": decision["args"], "result": "accepted"},
        ]
        return {"proposal": proposal, "steps": steps}

    def after_submit(state: CuratorState) -> str:
        return END if state["proposal"] is not None else "agent"

    def nudge(state: CuratorState) -> dict:
        return {"messages": [HumanMessage(content=NUDGE)], "nudged": True}

    def give_up(state: CuratorState) -> dict:
        return {"stop_reason": "answered without calling submit_decision"}

    graph = StateGraph(CuratorState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("submit", submit)
    graph.add_node("nudge", nudge)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", after_agent, ["tools", "submit", "nudge", "give_up", END]
    )
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("submit", after_submit, ["agent", END])
    graph.add_edge("nudge", "agent")
    graph.add_edge("give_up", END)
    return graph.compile()


def recursion_limit(max_turns: int) -> int:
    """LangGraph's own step cap, as a backstop above our turn limit."""
    return 3 * max_turns + 10
