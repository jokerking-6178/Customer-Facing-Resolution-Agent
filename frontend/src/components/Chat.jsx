import { useState } from "react";

export default function Chat({ messages, onSend, streaming, bottomRef }) {
  const [text, setText] = useState("");

  function submit(e) {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  }

  return (
    <section className="chat">
      <div className="chat__scroll">
        {messages.length === 0 && (
          <div className="chat__empty">
            Pick a customer and start the conversation — or click a demo scenario above.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble bubble--${m.role === "customer" ? "user" : "bot"}`}>
            {m.content || (streaming && i === messages.length - 1 ? "…" : "")}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form className="chat__input" onSubmit={submit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={streaming ? "SkyAssist is replying…" : "Type a message…"}
          disabled={streaming}
        />
        <button type="submit" disabled={streaming || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
