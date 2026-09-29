import { useState } from "react";
import { api } from "../api";

/**
 * Chat UI for talking to the finance agent.
 *
 * NOTE: this calls POST /chat on the backend, which doesn't exist yet —
 * that's the next piece to build (the LLM tool-calling loop). The UI is
 * wired up now so it's a drop-in once that endpoint is live.
 */
export default function Chat() {
  const [messages, setMessages] = useState([
    { role: "assistant", text: "Ask me about your spending — e.g. \"how much did I spend on food last month?\"" },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

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
        { role: "assistant", text: `(backend /chat isn't built yet — ${e.message})` },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="chat">
      <h3>Ask your finance agent</h3>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.text}
          </div>
        ))}
      </div>
      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Ask a question about your finances..."
          disabled={sending}
        />
        <button onClick={sendMessage} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
