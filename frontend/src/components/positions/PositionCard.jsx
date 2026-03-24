import Badge from '../ui/Badge';
import Card from '../ui/Card';
import { fmtCurrency } from '../../lib/format';

export default function PositionCard({ position }) {
  const pnl = Number(position?.pnl || 0);
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-zinc-400">{position?.instrument}</p>
          <p className="text-lg font-semibold">{position?.side?.toUpperCase()} · {position?.qty}</p>
        </div>
        <Badge variant={pnl >= 0 ? 'bullish' : 'bearish'}>{fmtCurrency(pnl)}</Badge>
      </div>
      <div className="mt-2 text-xs text-zinc-400">Open {fmtCurrency(position?.openPrice)} → Now {fmtCurrency(position?.currentPrice)}</div>
    </Card>
  );
}
