export default function Skeleton({ width = '100%', height = '1rem', rounded = '0.5rem', className = '' }) {
  return (
    <div
      className={`animate-pulse bg-zinc-800 ${className}`}
      style={{ width, height, borderRadius: rounded }}
    />
  );
}
