const STATUS = {
  executed: { label: "executed", cls: "a-executed" },
  declined: { label: "declined", cls: "a-declined" },
  escalated: { label: "escalated", cls: "a-escalated" },
  clarified: { label: "asked", cls: "a-clarified" },
};

function friendly(type) {
  return String(type).replaceAll("_", " ");
}

export default function ActionRecord({ actions, sessionId, ticket }) {
  return (
    <aside className="record">
      <h2 className="record__title">Action record</h2>
      {sessionId && <p className="record__session">{sessionId}</p>}
      {ticket && (
        <p className={`record__ticket record__ticket--${ticket.priority}`}>
          escalation ticket <strong>{ticket.ticket_id}</strong> · {ticket.priority} priority
        </p>
      )}
      {actions.length === 0 && (
        <p className="record__empty">
          Every action the agent takes, declines, or escalates is logged here with the rule
          that authorized it.
        </p>
      )}
      <div className="record__list">
        {actions.map((a, i) => {
          const s = STATUS[a.status] || STATUS.executed;
          return (
            <div key={a.id ?? i} className={`record__item ${s.cls}`}>
              <div className="record__item-head">
                <span className="record__type">{friendly(a.type)}</span>
                <span className={`record__status ${s.cls}`}>{s.label}</span>
              </div>
              {a.detail && <p className="record__detail">{a.detail}</p>}
              {a.rule && <p className="record__rule">rule: {a.rule}</p>}
              {a.ticket_id && (
                <p className="record__rule">ticket: {a.ticket_id}</p>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
