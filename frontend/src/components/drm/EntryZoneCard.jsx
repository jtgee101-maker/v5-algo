import Badge from '../ui/Badge';

export default function EntryZoneCard({ signal }) {
  return (
    <div className="border border-zinc-700 rounded-lg p-4 bg-zinc-900/60">
      <div className="flex items-center justify-between">
        <p className="font-semibold">{signal.bias?.toUpperCase()} setup</p>
        <Badge variant={signal.confidence === 'high' ? 'high' : 'medium'}>{signal.confidence}</Badge>
      </div>
      <p className="text-sm mt-2">Entry {signal.entry_zone?.low} - {signal.entry_zone?.high} (ideal {signal.entry_zone?.ideal})</p>
      <p className="text-xs text-zinc-400 mt-1">T1 {signal.targets?.t1} · T2 {signal.targets?.t2} · Stop {signal.stop_loss} · R:R {signal.risk_reward}</p>
    </div>
  );
}
