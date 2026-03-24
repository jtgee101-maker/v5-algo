export default function ProgressRing({ value = 0, max = 100, size = 80, color = '#3b82f6', label }) {
  const stroke = 8;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const offset = c - (pct / 100) * c;

  return (
    <div className="inline-flex flex-col items-center gap-2">
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#3f3f46" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x="50%" y="50%" fill="#fafafa" textAnchor="middle" dominantBaseline="middle" className="font-mono text-xs">
          {pct.toFixed(0)}%
        </text>
      </svg>
      {label ? <span className="text-xs text-zinc-400">{label}</span> : null}
    </div>
  );
}
