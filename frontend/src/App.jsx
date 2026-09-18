import { useEffect, useRef, useState } from "react";
import { streamChat, fetchJSON } from "./api.js";
import Sidebar from "./components/Sidebar.jsx";
import Chat from "./components/Chat.jsx";
import SentimentChip from "./components/SentimentChip.jsx";
import ActionRecord from "./components/ActionRecord.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";

const PRESETS = [
  {
    customerId: "priya_nair",
    label: "Scenario 1 · Priya",
    summary: "Cancelled flight, furious, wants refund + free upgrade",
    message:
      "My flight SK-204 got cancelled and I am furious! I want a full cash refund and a free upgrade to business class on my return flight for the trouble.",
  },
  {
    customerId: "arvind_kulkarni",
    label: "Scenario 2 · Arvind",
    summary: "4h delay, missed meeting, demands a hotel",
    message:
      "This delay ruined my whole day — my flight SK-118 is delayed 4 hours and I missed my connecting meeting. I want hotel accommodation since it's been such a long delay.",
  },
  {
    customerId: "meher_kaur",
    label: "Scenario 3 · Meher",
    summary: "6h delay, full-night hotel + ₹2,000 fare waiver",
    message:
      "My flight SK-305 is delayed 6 hours. I want a full night's hotel stay rather than coverage for just the delayed hours, and I want to be moved onto a different, higher-fare flight instead of waiting — the fare difference for that flight is ₹2,000.",
  },
];

const THEME_KEY = "skyassist-theme";

function readTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || "auto";
  } catch {
    return "auto"; // private mode / blocked storage
  }
}

export default function App() {
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sentiment, setSentiment] = useState(null);
  const [actions, setActions] = useState([]);
  const [ticket, setTicket] = useState(null);
  const [streaming, setStreaming] = useState(false);
  const [health, setHealth] = useState(null);
  const [theme, setTheme] = useState(readTheme);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    fetchJSON("/api/customers")
      .then((list) => {
        setCustomers(list);
        if (list.length) setCustomerId((cur) => cur ?? list[0].id);
      })
      .catch(() => {});
    fetchJSON("/healthz").then(setHealth).catch(() => {});
  }, []);

  // Apply the theme choice to <html> and remember it.
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* not fatal — the theme still applies for this page view */
    }
  }, [theme]);

  // Scroll the chat pane itself; scrollIntoView() would also scroll the
  // document and drag the header off-screen.
  useEffect(() => {
    const el = bottomRef.current?.parentElement;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function reset(id) {
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

  function switchCustomer(id) {
    if (id === customerId) return;
    reset(id);
  }

  function runScenario(preset) {
    if (preset.customerId !== customerId) {
      reset(preset.customerId);
      // Let the reset commit before the request goes out.
      setTimeout(() => send(preset.message, preset.customerId), 0);
    } else {
      send(preset.message);
    }
  }

  async function send(message, forCustomer) {
    const cid = forCustomer || customerId;
    if (!cid || streaming || !message.trim()) return;

    setMessages((m) => [
      ...m,
      { role: "customer", content: message, ts: Date.now() },
      { role: "agent", content: "", ts: Date.now(), actions: [] },
    ]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    // The session id arrives in the first SSE frame; state is still null on a
    // session's first turn, so track it locally rather than via a stale closure.
    let liveSessionId = forCustomer ? null : sessionId;

    await streamChat(
      { sessionId: liveSessionId, customerId: cid, message, signal: controller.signal },
      {
        session: (d) => {
          liveSessionId = d.session_id;
          setSessionId(d.session_id);
        },
        sentiment: (d) => setSentiment(d),
        token: (d) =>
          setMessages((m) => {
            const next = [...m];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, content: last.content + d.text };
            return next;
          }),
        action: (d) => {
          setActions((a) => [...a, d]);
          // Also attach it to the reply it belongs to, so each turn shows
          // what it actually did.
          setMessages((m) => {
            const next = [...m];
            const last = next[next.length - 1];
            if (last?.role === "agent") {
              next[next.length - 1] = { ...last, actions: [...(last.actions || []), d] };
            }
            return next;
          });
        },
        ticket: (d) => setTicket(d),
        done: async () => {
          if (!liveSessionId) return;
          try {
            setActions(await fetchJSON(`/api/actions?session_id=${liveSessionId}`));
          } catch {
            /* keep the streamed events */
          }
        },
        error: (d) =>
          setMessages((m) => {
            const next = [...m];
            next[next.length - 1] = {
              ...next[next.length - 1],
              content: `Sorry — something went wrong on our side: ${
                d.detail || "unknown error"
              }`,
            };
            return next;
          }),
      }
    );

    abortRef.current = null;
    setStreaming(false);
  }

  const customer = customers.find((c) => c.id === customerId);
  const turns = messages.filter((m) => m.role === "customer").length;

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="brand__mark">SA</span>
          <span>
            <div className="brand__name">SkyAssist</div>
            <div className="brand__sub">disruption desk</div>
          </span>
        </div>

        <div className="header__right">
          {sentiment && <SentimentChip sentiment={sentiment.sentiment} />}
          {sentiment?.intent && (
            <span className="meta-chip">
              intent: <b>{sentiment.intent}</b>
            </span>
          )}
          {health && (
            <span className="meta-chip">
              engine: <b>{health.llm_provider}</b>
            </span>
          )}
          <ThemeToggle theme={theme} setTheme={setTheme} />
        </div>
      </header>

      <div className="workspace">
        <Sidebar
          customers={customers}
          customerId={customerId}
          onSelect={switchCustomer}
          sessionId={sessionId}
          turns={turns}
          exerciseDate={health?.exercise_date}
          scenarios={PRESETS}
          onScenario={runScenario}
          streaming={streaming}
        />

        <Chat
          messages={messages}
          onSend={send}
          streaming={streaming}
          bottomRef={bottomRef}
          customer={customer}
        />

        <ActionRecord actions={actions} sessionId={sessionId} ticket={ticket} />
      </div>
    </div>
  );
}
