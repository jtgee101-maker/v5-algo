export default function MiniSparkline({ points = [] }) {
  if (!points.length) return <div className="h-10 text-xs text-zinc-500">No data</div>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const norm = points.map((p, i) => `${(i / (points.length - 1 || 1)) * 100},${100 - ((p - min) / (max - min || 1)) * 100}`).join(' ');
  return (
    <svg viewBox="0 0 100 100" className="w-full h-10">
      <polyline fill="none" stroke="#3b82f6" strokeWidth="2" points={norm} />
    </svg>
  );
}
