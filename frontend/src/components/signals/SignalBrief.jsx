import Badge from '../ui/Badge';

export default function SignalBrief({ signal, onSelect }) {
  return (
    <button onClick={onSelect} className="w-full text-left card hover:bg-zinc-700/50">
      <div className="flex items-center justify-between">
        <p className="font-medium">{signal.symbol} · {signal.side || signal.bias}</p>
        <Badge variant={signal.confidence === 'high' ? 'high' : 'medium'}>{signal.confidence || 'n/a'}</Badge>
      </div>
      <p className="text-xs text-zinc-400 mt-1">{signal.strategy_name || 'DRM'}</p>
    </button>
  );
}
