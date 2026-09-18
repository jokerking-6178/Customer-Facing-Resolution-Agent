function initials(name) {
  return String(name || "")
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function Sidebar({
  customers,
  customerId,
  onSelect,
  sessionId,
  turns,
  exerciseDate,
  scenarios,
  onScenario,
  streaming,
}) {
  return (
    <aside className="sidebar">
      <div>
        <div className="side-label">Customer</div>
        {customers.map((c) => {
          const on = c.id === customerId;
          return (
            <button
              key={c.id}
              className={`cust${on ? " cust--on" : ""}`}
              onClick={() => onSelect(c.id)}
              aria-pressed={on}
            >
              <span className="cust__avatar">{initials(c.name)}</span>
              <span>
                <span className="cust__name">{c.name}</span>
                <span className="cust__row">
                  <span className="tier">{c.loyalty_tier}</span>
                  <span className="cust__pnr">{c.booking_reference}</span>
                </span>
                {c.flight && (
                  <span className="cust__flight">
                    {c.flight} · <em>{c.status_summary}</em>
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      {customerId && (
        <div>
          <div className="side-label">Session</div>
          <div className="card">
            <div className="card__row">
              <span>id</span>
              <b>{sessionId || "not started"}</b>
            </div>
            <div className="card__row">
              <span>turns</span>
              <b>{turns}</b>
            </div>
            <div className="card__row">
              <span>exercise date</span>
              <b>{exerciseDate || "—"}</b>
            </div>
          </div>
        </div>
      )}

      <div>
        <div className="side-label">Demo scenarios</div>
        {scenarios.map((s) => (
          <button
            key={s.label}
            className="scenario"
            disabled={streaming}
            title={s.message}
            onClick={() => onScenario(s)}
          >
            <span className="scenario__no">{s.label}</span>
            <span className="scenario__desc">{s.summary}</span>
          </button>
        ))}
      </div>

      <div className="sidebar__foot">
        SkyAssist · assignment 3 prototype
        <br />
        every action policy-validated
      </div>
    </aside>
  );
}
