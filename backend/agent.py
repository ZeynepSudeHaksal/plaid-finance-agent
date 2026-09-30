"""
The agent loop: sends the conversation to Claude with the tool
definitions, executes whichever tools Claude decides to call against
the local database, feeds results back, and repeats until Claude
returns a final text answer instead of another tool call.
"""
import os
from datetime import date

import anthropic
from sqlalchemy.orm import Session

from agent_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 5  # safety cap so a confused loop can't run forever

SYSTEM_PROMPT = f"""You are a personal finance assistant. You have access to \
tools that query the user's real (Plaid Sandbox) transaction data. \
Today's date is {date.today().isoformat()}.

When answering:
- Always use a tool to get real numbers before answering questions about \
spending, categories, budgets, or trends - never guess or make up figures.
- Be concise and specific: cite actual dollar amounts and categories from \
tool results.
- If a question is ambiguous about date range (e.g. "this month"), assume \
the current calendar month unless the user says otherwise.
- If tool results are empty, say so plainly rather than inventing data.
"""


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
    return anthropic.Anthropic(api_key=api_key)


def _execute_tool(db: Session, tool_name: str, tool_input: dict, user_id: int):
    """
    Look up the tool function by name and call it with the DB session,
    args, and user_id. user_id is injected here rather than coming from
    the LLM's tool_input - the model never sees or controls it.
    """
    fn = TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(db=db, user_id=user_id, **tool_input)
    except Exception as e:
        return {"error": str(e)}


MAX_HISTORY_TURNS = 12  # keep context from growing unbounded over a long session


def run_agent(db: Session, user_message: str, user_id: int, history: list = None) -> tuple:
    """
    Runs one user turn through the tool-calling loop.

    `history` is a plain list of {"role": "user"|"assistant", "content": str}
    dicts from prior turns - final text only, not the intermediate
    tool-call/tool-result blocks. That's intentionally lossy: the model
    needs conversational context ("what about just dining?"), not a replay
    of exactly which tools it called last time.

    Returns (reply_text, updated_history) - the caller is responsible for
    persisting updated_history for the next call.
    """
    client = _get_client()
    history = history or []

    # Working message list for THIS turn's tool-calling loop: prior turns
    # (plain text) plus the new user message.
    messages = [dict(m) for m in history] + [{"role": "user", "content": user_message}]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text_parts = [block.text for block in response.content if block.type == "text"]
            reply = "\n".join(text_parts).strip()

            updated_history = history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": reply},
            ]
            # Trim from the oldest turns if we've grown past the cap.
            if len(updated_history) > MAX_HISTORY_TURNS * 2:
                updated_history = updated_history[-MAX_HISTORY_TURNS * 2 :]

            return reply, updated_history

        # Claude wants to call one or more tools - execute them and
        # continue the loop. These intermediate blocks live only in
        # `messages` for this turn; they are NOT saved into history.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _execute_tool(db, block.name, block.input, user_id)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    fallback = "I wasn't able to work out an answer within the tool-call limit - try rephrasing the question."
    return fallback, history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": fallback},
    ]