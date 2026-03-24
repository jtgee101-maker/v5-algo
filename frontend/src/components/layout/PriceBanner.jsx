import { useRef } from 'react';
import Badge from '../ui/Badge';
import { useMarketData } from '../../hooks/useMarketData';

export default function PriceBanner() {
  const { data, isLoading } = useMarketData();
  const prices = Object.values(data?.prices ?? {});
  const previousRef = useRef({});

  return (
    <div className="sticky top-14 z-20 bg-zinc-900/80 backdrop-blur border-b border-zinc-800 px-6 py-2">
      {isLoading ? (
        <p className="text-zinc-500 text-sm">Loading prices...</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
          {prices.map((item) => {
            const prev = previousRef.current[item.symbol];
            const changed = typeof prev === 'number' && prev !== Number(item.price);
            previousRef.current[item.symbol] = Number(item.price);
            return (
              <div key={item.symbol} className={`rounded-lg border border-zinc-800 px-2 py-1.5 bg-zinc-900/70 transition-colors ${changed ? 'bg-blue-500/10' : ''}`}>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-zinc-300">{item.symbol}</span>
                  <Badge variant={item.change_24h_pct >= 0 ? 'bullish' : 'bearish'} size="sm">
                    {item.change_24h_pct?.toFixed(2)}%
                  </Badge>
                </div>
                <div className="font-mono text-sm mt-1">${Number(item.price).toFixed(2)}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
