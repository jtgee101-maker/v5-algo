import { sentimentToVariant } from '../../lib/format';

const color = {
  bullish: 'shadow-[0_0_40px_rgba(34,197,94,0.45)] bg-green-500/20 border-green-500/50',
  bearish: 'shadow-[0_0_40px_rgba(239,68,68,0.45)] bg-red-500/20 border-red-500/50',
  neutral: 'shadow-[0_0_30px_rgba(113,113,122,0.35)] bg-zinc-500/20 border-zinc-500/50',
};

export default function SentimentOrb({ sentiment = 'neutral', score = 0 }) {
  const v = sentimentToVariant(sentiment);
  return (
    <div className="flex items-center gap-4">
      <div className={`h-16 w-16 rounded-full border ${color[v]}`} />
      <div className="flex-1">
        <p className="text-sm font-medium">{sentiment}</p>
        <div className="h-2 bg-zinc-800 rounded-full mt-2 overflow-hidden">
          <div className={`h-2 ${v === 'bullish' ? 'bg-green-500' : v === 'bearish' ? 'bg-red-500' : 'bg-zinc-500'}`} style={{ width: `${Math.max(0, Math.min(100, Number(score) * 100))}%` }} />
        </div>
      </div>
    </div>
  );
}
