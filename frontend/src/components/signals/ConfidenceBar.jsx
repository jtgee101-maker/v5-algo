export default function ConfidenceBar({ score = 0, max = 5 }) {
  const pct = Math.max(0, Math.min(100, (score / max) * 100));
  return <div className="h-2 rounded-full bg-zinc-800"><div className="h-2 rounded-full bg-amber-500" style={{ width: `${pct}%` }} /></div>;
}
