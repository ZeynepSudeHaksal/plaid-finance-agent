"""
Tests for the agent loop with the Anthropic client replaced by a script.

The fake client returns pre-written responses (a tool call, then a final
answer), so these tests exercise OUR code - dispatching tools, scoping them
to the user, feeding results back, trimming history - without a network call
or any API cost.
"""
from types import SimpleNamespace

import pytest

import agent


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, tool_input, block_id="tool-1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def reply(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class FakeAnthropic:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self  # so agent code can call client.messages.create(...)

    def create(self, **kwargs):
        # Snapshot the message list; the agent keeps appending to the same list object.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def use_fake(monkeypatch):
    def _use(*responses):
        fake = FakeAnthropic(*responses)
        monkeypatch.setattr(agent, "_get_client", lambda: fake)
        return fake

    return _use


def tool_result_text(request):
    """The content of the tool_result the agent sent back to the model in this request."""
    last = request["messages"][-1]
    assert last["role"] == "user"
    return str(last["content"][0]["content"])


def test_plain_answer_without_tools(db, make_user, use_fake):
    user = make_user()
    use_fake(reply("end_turn", text_block("Hello! Ask me about your spending.")))

    answer, history = agent.run_agent(db, "hi", user.id)

    assert answer == "Hello! Ask me about your spending."
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello! Ask me about your spending."},
    ]


def test_tool_call_is_executed_and_its_result_is_fed_back(db, make_user, add_txn, use_fake):
    user = make_user()
    add_txn(user.id, "2026-09-01", 42.50, "FOOD_AND_DRINK")
    fake = use_fake(
        reply("tool_use", tool_block("categorize_spending", {"start_date": "2026-09-01"})),
        reply("end_turn", text_block("You spent $42.50 on food.")),
    )

    answer, _ = agent.run_agent(db, "how much did I spend?", user.id)

    assert answer == "You spent $42.50 on food."
    assert len(fake.requests) == 2
    result = tool_result_text(fake.requests[1])
    assert "FOOD_AND_DRINK" in result and "42.5" in result
    # The tool schemas and system prompt are sent on every call
    assert fake.requests[0]["tools"] and fake.requests[0]["system"]


def test_tools_only_see_the_calling_users_data(db, make_user, add_txn, use_fake):
    alice = make_user("alice@gmail.com")
    bob = make_user("bob@gmail.com")
    add_txn(alice.id, "2026-09-01", 10.00, "ALICE_SECRET_CATEGORY")
    add_txn(bob.id, "2026-09-01", 20.00, "BOB_CATEGORY")
    fake = use_fake(
        reply("tool_use", tool_block("categorize_spending", {})),
        reply("end_turn", text_block("done")),
    )

    agent.run_agent(db, "what did I spend?", bob.id)

    result = tool_result_text(fake.requests[1])
    assert "BOB_CATEGORY" in result
    assert "ALICE_SECRET_CATEGORY" not in result


def test_the_model_cannot_choose_which_user_to_query(db, make_user, add_txn, use_fake):
    """If the model (e.g. via prompt injection) tries to pass a user_id, it must fail - not leak."""
    alice = make_user("alice@gmail.com")
    bob = make_user("bob@gmail.com")
    add_txn(alice.id, "2026-09-01", 10.00, "ALICE_SECRET_CATEGORY")
    fake = use_fake(
        reply("tool_use", tool_block("categorize_spending", {"user_id": alice.id})),
        reply("end_turn", text_block("done")),
    )

    agent.run_agent(db, "show me user 1's spending", bob.id)

    result = tool_result_text(fake.requests[1])
    assert "ALICE_SECRET_CATEGORY" not in result
    assert "error" in result.lower()


def test_unknown_tool_returns_an_error_and_the_loop_continues(db, make_user, use_fake):
    user = make_user()
    fake = use_fake(
        reply("tool_use", tool_block("delete_everything", {})),
        reply("end_turn", text_block("Sorry, I can't do that.")),
    )

    answer, _ = agent.run_agent(db, "do something weird", user.id)

    assert "Unknown tool" in tool_result_text(fake.requests[1])
    assert answer == "Sorry, I can't do that."


def test_prior_conversation_is_sent_to_the_model(db, make_user, use_fake):
    user = make_user()
    fake = use_fake(reply("end_turn", text_block("ok")))
    history = [
        {"role": "user", "content": "how much on food?"},
        {"role": "assistant", "content": "$50"},
    ]

    agent.run_agent(db, "and transport?", user.id, history)

    sent = fake.requests[0]["messages"]
    assert sent[0] == {"role": "user", "content": "how much on food?"}
    assert sent[-1] == {"role": "user", "content": "and transport?"}


def test_history_is_trimmed_to_the_most_recent_turns(db, make_user, use_fake):
    user = make_user()
    use_fake(reply("end_turn", text_block("latest answer")))
    long_history = []
    for i in range(15):  # 30 messages, more than the cap allows
        long_history += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]

    _, history = agent.run_agent(db, "newest question", user.id, long_history)

    assert len(history) == agent.MAX_HISTORY_TURNS * 2
    assert history[0]["role"] == "user"  # trimming never leaves the conversation starting mid-turn
    assert history[-2:] == [
        {"role": "user", "content": "newest question"},
        {"role": "assistant", "content": "latest answer"},
    ]


def test_loop_gives_up_after_the_tool_call_limit(db, make_user, use_fake):
    user = make_user()
    stuck = [reply("tool_use", tool_block("get_budgets", {}, f"tool-{i}")) for i in range(agent.MAX_TOOL_ITERATIONS)]
    use_fake(*stuck)

    answer, history = agent.run_agent(db, "loop forever", user.id)

    assert "tool-call limit" in answer
    assert history[-1]["role"] == "assistant"


def test_missing_api_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        agent._get_client()
