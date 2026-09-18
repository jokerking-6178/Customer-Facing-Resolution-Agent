import { useState } from "react";

const FILTERS = ["all", "executed", "declined", "escalated"];

function label(type) {
  return String(type).replaceAll("_", " ");
}

export default function ActionRecord({ actions, sessionId, ticket }) {
  const [filter, setFilter] = useState("all");

  const counts = actions.reduce(
    (acc, a) => ({ ...acc, [a.status]: (acc[a.status] || 0) + 1 }),
    {}
  );
  const shown = filter === "all" ? actions : actions.filter((a) => a.status === filter);

  return (
    <aside className="record">
      <div className="record__head">
        <h2 className="record__title">Action record</h2>
        <p className="record__sub">
          {sessionId ? `${sessionId} · ` : ""}every entry cites its rule
        </p>
      </div>

      <div className="stats">
        <div className="stat stat--executed">
          <div className="stat__n">{counts.executed || 0}</div>
          <div className="stat__l">Executed</div>
        </div>
        <div className="stat stat--declined">
          <div className="stat__n">{counts.declined || 0}</div>
          <div className="stat__l">Declined</div>
        </div>
        <div className="stat stat--escalated">
          <div className="stat__n">{counts.escalated || 0}</div>
          <div className="stat__l">Escalated</div>
        </div>
      </div>

      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f}
            className={`filter${filter === f ? " filter--on" : ""}`}
            onClick={() => setFilter(f)}
            aria-pressed={filter === f}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="record__list">
        {ticket && (
          <div className={`ticket${ticket.priority === "normal" ? " ticket--normal" : ""}`}>
            escalation ticket <b>{ticket.ticket_id}</b>
            <br />
            {ticket.priority} priority · handed to a human agent
          </div>
        )}

        {shown.length === 0 && (
          <p className="record__empty">
            {actions.length === 0
              ? "Nothing yet. Every action the agent takes, declines, or escalates is logged here with the rule that authorised it."
              : `No ${filter} actions in this session.`}
          </p>
        )}

        {shown.map((a, i) => (
          <div key={a.id ?? i} className={`entry entry--${a.status}`}>
            <div className="entry__head">
              <span className="entry__type">{label(a.type)}</span>
              <span className="entry__badge">{a.status}</span>
            </div>
            {a.detail && <p className="entry__detail">{a.detail}</p>}
            {a.rule && (
              <span className="entry__rule">
                rule: <b>{a.rule}</b>
              </span>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
