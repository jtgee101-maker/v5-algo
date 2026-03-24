import AnimatedNumber from './AnimatedNumber';

export default function PriceTag({ value = 0, change = 0, size = 'md', animated = true }) {
  const cls = size === 'lg' ? 'text-3xl' : size === 'sm' ? 'text-sm' : 'text-lg';
  const color = change > 0 ? 'text-profit' : change < 0 ? 'text-loss' : 'text-zinc-300';

  return (
    <span className={`font-mono ${cls} ${color}`}>
      {animated ? <AnimatedNumber value={value} prefix="$" decimals={2} /> : `$${value.toFixed(2)}`}
    </span>
  );
}
