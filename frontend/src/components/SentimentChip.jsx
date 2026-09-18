const STYLES = {
  calm: { label: "calm", cls: "s-calm" },
  frustrated: { label: "frustrated", cls: "s-frustrated" },
  angry: { label: "angry", cls: "s-angry" },
  confused: { label: "confused", cls: "s-confused" },
};

export default function SentimentChip({ sentiment, intent }) {
  const s = STYLES[sentiment] || STYLES.calm;
  return (
    <div className="sentiment">
      <span className={`sentiment__chip ${s.cls}`}>{s.label}</span>
      {intent && <span className="sentiment__intent">intent: {intent}</span>}
    </div>
  );
}
