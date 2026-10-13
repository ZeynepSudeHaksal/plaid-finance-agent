import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api";

const SAMPLE_QUESTIONS = [
  "How much did I spend on food last month?",
  "Anything unusual in my spending?",
  "Am I on track with my budgets this month?",
  "Compare this month to last month",
  "Forecast my spending for next month",
];

export default function Chat({ onBudgetChanged }) {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Ask about your spending — e.g. \"how much did I spend on food last month?\"",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [remaining, setRemaining] = useState(null);

  const startNewConversation = async () => {
    try {
      await api.resetChat();
    } catch {
      // If the reset call fails, still clear the local view - worst
      // case the backend's history lingers one extra turn, which the
      // next message will naturally overwrite anyway.
    }
    setMessages([
      {
        role: "assistant",
        text: "Ask about your spending — e.g. \"how much did I spend on food last month?\"",
      },
    ]);
  };

  const sendMessage = async (override) => {
    const text = (typeof override === "string" ? override : input).trim();
    if (!text || sending) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);

    try {
      const { reply, remaining_today } = await api.sendChatMessage(text);
      if (typeof remaining_today === "number") setRemaining(remaining_today);
      setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
      // The agent may have just set/changed a budget (set_budget tool) -
      // the reply doesn't say which tools ran, so just let the budget
      // panel re-check; it's one cheap GET, not worth tracking tool names
      // for.
      onBudgetChanged?.();
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `Couldn't reach the agent — ${e.message}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="chat">
      <div className="chat-header">
        <h3>Ask the agent</h3>
        <button className="ghost-button" onClick={startNewConversation} disabled={sending}>
          New conversation
        </button>
      </div>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.role === "assistant" ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
            ) : (
              m.text
            )}
          </div>
        ))}
        {sending && <div className="chat-bubble assistant hint">Thinking…</div>}
      </div>
      {messages.length === 1 && (
        <div className="chat-suggestions">
          {SAMPLE_QUESTIONS.map((q) => (
            <button key={q} type="button" className="chip" onClick={() => sendMessage(q)} disabled={sending}>
              {q}
            </button>
          ))}
        </div>
      )}
      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Ask a question about your finances…"
          disabled={sending}
        />
        <button onClick={() => sendMessage()} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
      {remaining !== null && (
        <p className="hint chat-quota">{remaining} message{remaining === 1 ? "" : "s"} left today</p>
      )}
    </section>
  );
}
