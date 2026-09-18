import { useState } from "react";

const CHIP_VERB = {
  executed: "done",
  declined: "declined",
  escalated: "escalated",
  clarified: "asked",
};

function label(type) {
  return String(type).replaceAll("_", " ");
}

function stamp(ts) {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function Chat({
  messages,
  onSend,
  streaming,
  bottomRef,
  customer,
}) {
  const [text, setText] = useState("");

  function submit(e) {
    e.preventDefault();
    if (!text.trim() || streaming) return;
    onSend(text.trim());
    setText("");
  }

  return (
    <section className="chat">
      <div className="chat__head">
        {customer ? (
          <>
            <span className="chat__who">{customer.name}</span>
            <span className="tier">{customer.loyalty_tier}</span>
            {customer.flight && (
              <>
                <span className="chat__sep">·</span>
                <span className="chat__route">
                  {customer.flight}
                  {customer.route_display ? ` · ${customer.route_display}` : ""}
                </span>
              </>
            )}
            {customer.status_summary && (
              <span className="chat__status">{customer.status_summary}</span>
            )}
          </>
        ) : (
          <span className="chat__route">Loading customers…</span>
        )}
        <span className="chat__note">agent executes only policy-validated actions</span>
      </div>

      <div className="chat__scroll">
        {messages.length === 0 && (
          <p className="chat__empty">
            Start the conversation, or run one of the demo scenarios from the
            left. Every reply is written from verdicts the policy engine
            produced — never from the model's own judgement.
          </p>
        )}

        {messages.map((m, i) => {
          const isCustomer = m.role === "customer";
          const waiting = streaming && !m.content && i === messages.length - 1;
          return (
            <div
              key={i}
              className={`turn turn--${isCustomer ? "customer" : "agent"}`}
            >
              <div className="bubble">
                {m.content || (waiting ? "…" : "")}
              </div>

              {!!m.actions?.length && (
                <div className="turn__chips">
                  {m.actions.map((a, j) => (
                    <span key={j} className={`chip chip--${a.status}`}>
                      {label(a.type)} · {CHIP_VERB[a.status] || a.status}
                    </span>
                  ))}
                </div>
              )}

              <span className="turn__stamp">
                {isCustomer ? customer?.name?.split(" ")[0] : "SkyAssist"}
                {m.ts ? ` · ${stamp(m.ts)}` : ""}
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <form className="chat__form" onSubmit={submit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={streaming ? "SkyAssist is replying…" : "Type a message…"}
          disabled={streaming}
          aria-label="Message"
        />
        <button type="submit" disabled={streaming || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
