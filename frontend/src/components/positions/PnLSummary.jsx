import AnimatedNumber from '../ui/AnimatedNumber';

export default function PnLSummary({ positions = [] }) {
  const total = positions.reduce((sum, p) => sum + Number(p.pnl || 0), 0);
  return (
    <div>
      <p className="text-xs text-zinc-500 uppercase tracking-wide">Open P&L</p>
      <p className={`font-mono text-3xl ${total >= 0 ? 'text-profit' : 'text-loss'}`}>
        <AnimatedNumber value={total} prefix="$" decimals={2} duration={0.4} />
      </p>
    </div>
  );
}
