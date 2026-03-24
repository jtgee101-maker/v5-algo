import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getCandles } from '../api/client';
import CandlestickChart from '../components/charts/CandlestickChart';

export default function Charts() {
  const [symbol, setSymbol] = useState('USOIL');
  const [resolution, setResolution] = useState('1h');
  const { data, isLoading, error } = useQuery({
    queryKey: ['candles', symbol, resolution],
    queryFn: () => getCandles(symbol, resolution, '5D'),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <select value={symbol} onChange={(e)=>setSymbol(e.target.value)} className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2">
          {['BTCUSD', 'NAS100', 'US30', 'EURUSD', 'XAUUSD', 'USOIL'].map((s) => <option key={s}>{s}</option>)}
        </select>
        {['15m', '1h', '4h'].map((r) => <button key={r} onClick={()=>setResolution(r)} className={`px-3 py-2 rounded-lg border ${r===resolution?'bg-zinc-700 border-zinc-500':'border-zinc-700'}`}>{r}</button>)}
      </div>
      {isLoading ? <div className="card">Loading chart...</div> : null}
      {error ? <div className="card">Unable to load candles.</div> : null}
      {data ? <CandlestickChart candles={data.candles || []} /> : null}
    </div>
  );
}
