export default function CustomerPicker({ customers, selected, onSelect }) {
  return (
    <div className="picker">
      <span className="picker__label">Talking as</span>
      {customers.map((c) => (
        <button
          key={c.id}
          className={`picker__card ${selected === c.id ? "is-selected" : ""}`}
          onClick={() => onSelect(c.id)}
        >
          <span className="picker__name">{c.name}</span>
          <span className={`tier tier--${c.loyalty_tier.toLowerCase()}`}>{c.loyalty_tier}</span>
          <span className="picker__pnr">{c.booking_reference}</span>
        </button>
      ))}
    </div>
  );
}
