import Badge from '../ui/Badge';

export default function FVGZone({ fvg }) {
  return (
    <div className="border border-zinc-700 rounded-lg p-3">
      <div className="flex items-center justify-between">
        <Badge variant={fvg.direction === 'bullish' ? 'bullish' : 'bearish'}>{fvg.direction}</Badge>
        <span className="font-mono text-xs">{fvg.low} - {fvg.high}</span>
      </div>
      <div className="h-2 rounded bg-zinc-800 mt-2 overflow-hidden">
        <div className="h-2 bg-blue-500" style={{ width: `${fvg.fill_pct || 0}%` }} />
      </div>
      <p className="mt-1 text-xs text-zinc-400">Fill {fvg.fill_pct ?? 0}% · Mid {fvg.mid}</p>
    </div>
  );
}
