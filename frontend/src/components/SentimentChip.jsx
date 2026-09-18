const KNOWN = ["calm", "frustrated", "angry", "confused"];

export default function SentimentChip({ sentiment }) {
  const s = KNOWN.includes(sentiment) ? sentiment : "calm";
  return (
    <span className={`sentiment sentiment--${s}`}>
      <span className="sentiment__dot" />
      {s}
    </span>
  );
}
