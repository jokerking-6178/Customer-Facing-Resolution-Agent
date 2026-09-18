import { useEffect, useRef, useState } from "react";
import { streamChat, fetchJSON } from "./api.js";
import CustomerPicker from "./components/CustomerPicker.jsx";
import Chat from "./components/Chat.jsx";
import SentimentChip from "./components/SentimentChip.jsx";
import ActionRecord from "./components/ActionRecord.jsx";

const PRESETS = [
  {
    label: "Scenario 1 · Priya",
    message:
      "My flight SK-204 got cancelled and I am furious! I want a full cash refund and a free upgrade to business class on my return flight for the trouble.",
  },
  {
    label: "Scenario 2 · Arvind",
    message:
      "This delay ruined my whole day — my flight SK-118 is delayed 4 hours and I missed my connecting meeting. I want hotel accommodation since it's been such a long delay.",
  },
  {
    label: "Scenario 3 · Meher",
    message:
      "My flight SK-305 is delayed 6 hours. I want a full night's hotel stay rather than coverage for just the delayed hours, and I want to be moved onto a different, higher-fare flight instead of waiting — the fare difference for that flight is ₹2,000.",
  },
];

export default function App() {
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sentiment, setSentiment] = useState(null);
  const [actions, setActions] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [health, setHealth] = useState(null);
  const [ticket, setTicket] = useState(null);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    fetchJSON("/api/customers").then(setCustomers).catch(() => {});
    fetchJSON("/healthz").then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function switchCustomer(id) {
    // Stop any in-flight stream, or its tokens land in the cleared thread.
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setCustomerId(id);
    setSessionId(null);
    setMessages([]);
    setSentiment(null);
    setActions([]);
    setTicket(null);
  }

  async function send(message) {
    if (!customerId || streaming || !message.trim()) return;
    setMessages((m) => [...m, { role: "customer", content: message }]);
    setMessages((m) => [...m, { role: "agent", content: "" }]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    // The session id arrives in the first SSE frame. `sessionId` from state is
    // still null on a session's first turn, so track it locally for the
    // refetch below rather than reading a stale closure.
    let liveSessionId = sessionId;

    await streamChat(
      { sessionId, customerId, message, signal: controller.signal },
      {
        session: (d) => {
          liveSessionId = d.session_id;
          setSessionId(d.session_id);
        },
        sentiment: (d) => setSentiment(d),
        token: (d) =>
          setMessages((m) => {
            const next = [...m];
            next[next.length - 1] = {
              role: "agent",
              content: next[next.length - 1].content + d.text,
            };
            return next;
          }),
        action: (d) => setActions((a) => [...a, d]),
        ticket: (d) => setTicket(d),
        done: async () => {
          if (!liveSessionId) return;
          try {
            setActions(await fetchJSON(`/api/actions?session_id=${liveSessionId}`));
          } catch {
            /* keep streamed events */
          }
        },
        error: (d) =>
          setMessages((m) => {
            const next = [...m];
            next[next.length - 1] = {
              role: "agent",
              content: `Sorry — something went wrong on our side: ${d.detail || "unknown error"}`,
            };
            return next;
          }),
      }
    );
    abortRef.current = null;
    setStreaming(false);
  }

  const customer = customers.find((c) => c.id === customerId);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>SkyAssist</h1>
          <p className="tagline">
            Airline disruption resolution agent{health?.exercise_date ? ` · ${health.exercise_date}` : ""}
            {health && <span className="provider"> · engine: {health.llm_provider}</span>}
          </p>
        </div>
        {sentiment && <SentimentChip sentiment={sentiment.sentiment} intent={sentiment.intent} />}
      </header>

      <CustomerPicker
        customers={customers}
        selected={customerId}
        onSelect={switchCustomer}
      />

      {customer && (
        <>
          <div className="presets">
            <span className="presets__label">Demo script:</span>
            {PRESETS.map((p) => (
              <button
                key={p.label}
                className="preset"
                disabled={streaming}
                title={p.message}
                onClick={() => send(p.message)}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="layout">
            <Chat
              messages={messages}
              onSend={send}
              streaming={streaming}
              bottomRef={bottomRef}
            />
            <ActionRecord actions={actions} sessionId={sessionId} ticket={ticket} />
          </div>
        </>
      )}
    </div>
  );
}
