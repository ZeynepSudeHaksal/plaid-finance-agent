import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api";

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Ask about your spending — e.g. \"how much did I spend on food last month?\"",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

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

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);

    try {
      const { reply } = await api.sendChatMessage(text);
      setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
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
      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Ask a question about your finances…"
          disabled={sending}
        />
        <button onClick={sendMessage} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
    </section>
  );
}