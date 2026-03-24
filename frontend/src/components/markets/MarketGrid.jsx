import SymbolCard from './SymbolCard';

export default function MarketGrid({ prices = {}, sessions = {} }) {
  const rows = Object.values(prices);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {rows.map((item) => (
        <SymbolCard
          key={item.symbol}
          symbol={item.symbol}
          price={item.price}
          change={item.change_24h_pct}
          session={sessions[item.symbol]}
          type={sessions[item.symbol]?.type}
        />
      ))}
    </div>
  );
}
