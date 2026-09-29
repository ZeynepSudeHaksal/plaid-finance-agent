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


def _execute_tool(db: Session, tool_name: str, tool_input: dict):
    """Look up the tool function by name and call it with the DB session + args."""
    fn = TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(db=db, **tool_input)
    except Exception as e:
        return {"error": str(e)}


def run_agent(db: Session, user_message: str) -> str:
    """
    Runs one user turn through the tool-calling loop and returns the
    agent's final text reply. Stateless across calls for now - no
    conversation history is kept between requests (see main.py note).
    """
    client = _get_client()
    messages = [{"role": "user", "content": user_message}]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            # Claude gave a final answer - collect any text blocks and return.
            text_parts = [block.text for block in response.content if block.type == "text"]
            return "\n".join(text_parts).strip()

        # Claude wants to call one or more tools. Append its request,
        # execute each tool, and append the results as a new message.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _execute_tool(db, block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return "I wasn't able to work out an answer within the tool-call limit - try rephrasing the question."
