const variantClass = {
  bullish: 'badge-bullish',
  bearish: 'badge-bearish',
  neutral: 'badge-neutral',
  high: 'badge-high',
  medium: 'badge-medium',
  low: 'badge-low',
  agent: 'badge-agent',
  live: 'badge-live',
  closed: 'badge-closed',
};

const sizeClass = { sm: 'px-2 py-0.5 text-[10px]', md: 'px-3 py-1 text-xs' };

export default function Badge({ children, variant = 'neutral', size = 'md' }) {
  return (
    <span className={`inline-flex items-center rounded-full font-medium ${variantClass[variant]} ${sizeClass[size]}`}>
      {children}
    </span>
  );
}
