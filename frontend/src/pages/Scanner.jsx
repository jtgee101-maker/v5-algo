import { useMemo, useState } from 'react';
import { runAnalysis } from '../api/client';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';

export default function Scanner() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const scan = async () => {
    setLoading(true);
    try {
      setResult(await runAnalysis());
    } finally {
      setLoading(false);
    }
  };

  const summary = useMemo(() => {
    const signals = result?.signals || [];
    const long = signals.filter((s) => `${s.bias}`.toLowerCase() === 'long').length;
    const short = signals.filter((s) => `${s.bias}`.toLowerCase() === 'short').length;
    const wait = Math.max(0, 6 - signals.length);
    return `${long} LONG · ${short} SHORT · ${wait} WAIT`;
  }, [result]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Scanner</h2>
          <p className="text-sm text-zinc-400 mt-1">{summary}</p>
        </div>
        <Button onClick={scan} loading={loading}>Run Analysis</Button>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {(result?.signals || []).map((s, i) => (
          <Card key={i}>
            <div className="flex justify-between items-center">
              <p className="font-semibold">{s.symbol}</p>
              <Badge variant={s.bias === 'long' ? 'bullish' : 'bearish'}>{s.bias}</Badge>
            </div>
            <p className="text-sm text-zinc-400 mt-2">Momentum: {s.momentum}</p>
            <p className="text-sm text-zinc-400">Confidence: {s.confidence} ({s.conf_score}/5)</p>
            <ul className="mt-2 text-sm list-disc list-inside text-zinc-300">
              {(s.reasoning || []).map((r) => <li key={r}>{r}</li>)}
            </ul>
          </Card>
        ))}
      </div>
      {!loading && !result?.signals?.length ? <Card>No scan results yet. Click Run Analysis.</Card> : null}
    </div>
  );
}
