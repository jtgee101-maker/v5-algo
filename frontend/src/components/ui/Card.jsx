export default function Card({ children, className = '', onClick, hover = false }) {
  return (
    <div
      onClick={onClick}
      className={`bg-zinc-800 border border-zinc-700 rounded-xl p-5 ${hover ? 'hover:bg-zinc-700/50 transition-colors' : ''} ${className}`}
    >
      {children}
    </div>
  );
}
