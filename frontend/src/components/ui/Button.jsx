const variantClass = {
  primary: 'bg-blue-600 hover:bg-blue-500 text-white',
  ghost: 'border border-zinc-700 hover:bg-zinc-800 text-zinc-300',
  danger: 'bg-red-600 hover:bg-red-500 text-white',
};

const sizeClass = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2.5 text-sm' };

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  onClick,
  disabled = false,
  loading = false,
  type = 'button',
  className = '',
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={`rounded-lg transition-colors ${variantClass[variant]} ${sizeClass[size]} disabled:opacity-60 disabled:cursor-not-allowed ${className}`}
    >
      {loading ? '⏳ Loading...' : children}
    </button>
  );
}
