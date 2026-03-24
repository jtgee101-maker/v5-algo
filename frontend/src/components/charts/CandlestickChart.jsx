import MiniSparkline from './MiniSparkline';

export default function CandlestickChart({ candles = [] }) {
  const closes = candles.map((c) => Number(c.c));
  return (
    <div className="card">
      <h3 className="font-semibold mb-2">Price Trend</h3>
      <MiniSparkline points={closes} />
      <div className="mt-3 max-h-72 overflow-auto">
        <table className="w-full text-xs">
          <thead className="text-zinc-400">
            <tr><th className="text-left">Time</th><th>O</th><th>H</th><th>L</th><th>C</th></tr>
          </thead>
          <tbody>
            {candles.slice(-20).reverse().map((c) => (
              <tr key={c.t} className="border-t border-zinc-800">
                <td>{c.t}</td><td>{c.o}</td><td>{c.h}</td><td>{c.l}</td><td>{c.c}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
