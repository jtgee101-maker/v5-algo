import { useState } from 'react';
import { useDRMAnalysis } from '../hooks/useDRM';
import { useAppStore } from '../store/appStore';
import FVGZone from '../components/drm/FVGZone';
import DisplacementEvent from '../components/drm/DisplacementEvent';
import EntryZoneCard from '../components/drm/EntryZoneCard';
import ProbabilityRing from '../components/drm/ProbabilityRing';
import ProbabilityCalculator from '../components/drm/ProbabilityCalculator';
import Card from '../components/ui/Card';

const SYMBOLS = ['BTCUSD', 'NAS100', 'US30', 'EURUSD', 'XAUUSD', 'USOIL'];

export default function DRM() {
  const defaultSymbol = useAppStore((s) => s.selectedSymbol);
  const [symbol, setSymbol] = useState(defaultSymbol);
  const { data, isLoading, error } = useDRMAnalysis(symbol);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {SYMBOLS.map((s) => (
          <button key={s} onClick={() => setSymbol(s)} className={`px-3 py-2 rounded-lg border ${s === symbol ? 'bg-zinc-700 border-zinc-500' : 'border-zinc-700 bg-zinc-900'}`}>{s}</button>
        ))}
      </div>
      {isLoading ? <Card>Loading {symbol}...</Card> : null}
      {error ? <Card>Unable to load DRM data.</Card> : null}
      {data ? (
        <>
          <Card>
            <h2 className="text-xl font-semibold">{data.symbol} DRM Overview</h2>
            <p className="text-sm text-zinc-400 mt-2">Price {data.current_price} · ATR {data.atr} · Volatility {data.volatility_regime}</p>
          </Card>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card><h3 className="font-semibold mb-3">Displacements</h3><div className="space-y-2">{(data.displacements || []).map((d, i) => <DisplacementEvent key={i} event={d} />)}</div></Card>
            <Card><h3 className="font-semibold mb-3">Fair Value Gaps</h3><div className="space-y-2">{(data.fair_value_gaps || []).map((f, i) => <FVGZone key={i} fvg={f} />)}</div></Card>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 space-y-3">{(data.signals || []).map((s, i) => <EntryZoneCard key={i} signal={s} />)}</div>
            <Card><h3 className="font-semibold mb-3">Touch Probabilities</h3>{(data.signals || []).slice(0, 2).map((s, i) => <div key={i} className="mb-3 flex gap-3"><ProbabilityRing value={s.touch_prob_target || 0} label="Target" /><ProbabilityRing value={s.touch_prob_stop || 0} label="Stop" /></div>)}</Card>
          </div>
          <ProbabilityCalculator />
        </>
      ) : null}
    </div>
  );
}
