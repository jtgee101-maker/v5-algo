import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { approveSignal, rejectSignal } from '../../api/client';
import { useDRMScan } from '../../hooks/useDRM';
import { useAppStore } from '../../store/appStore';
import Button from '../ui/Button';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import ScanProgress from '../agents/ScanProgress';

export default function DRMPanel() {
  const [results, setResults] = useState([]);
  const scan = useDRMScan();
  const autoScan = useAppStore((s) => s.autoScan);
  const setAutoScan = useAppStore((s) => s.setAutoScan);
  const approve = useMutation({ mutationFn: (id) => approveSignal(id) });
  const reject = useMutation({ mutationFn: (id) => rejectSignal(id) });

  const runScan = async () => {
    const data = await scan.mutateAsync();
    setResults(data?.all_signals || data?.signals || []);
  };

  useEffect(() => {
    if (!autoScan) return undefined;
    runScan();
    const timer = setInterval(runScan, 120_000);
    return () => clearInterval(timer);
  }, [autoScan]);

  return (
    <Card className="border-l-4 border-l-purple-500">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold">DRM Agent Insights</h3>
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-400 flex items-center gap-1">
            <input type="checkbox" checked={autoScan} onChange={(e) => setAutoScan(e.target.checked)} /> Auto
          </label>
          <Button onClick={runScan} loading={scan.isPending}>Scan Now</Button>
        </div>
      </div>
      <ScanProgress isScanning={scan.isPending} symbolCount={6} />
      {!scan.isPending && results.length === 0 ? (
        <p className="text-sm text-zinc-500 mt-2">No signals — agents will scan in 2min.</p>
      ) : null}
      <div className="mt-3 space-y-3 max-h-80 overflow-auto pr-1">
        {results.map((signal, idx) => (
          <div key={`${signal.symbol}-${idx}`} className="border border-zinc-700 rounded-lg p-3 bg-zinc-900/50">
            <div className="flex items-center justify-between mb-2">
              <p className="font-medium">{signal.symbol} · {signal.bias?.toUpperCase()}</p>
              <Badge variant={signal.confidence === 'high' ? 'high' : 'medium'}>{signal.confidence || 'n/a'}</Badge>
            </div>
            <p className="text-xs text-zinc-400">Entry {signal.entry_zone?.ideal ?? '-'} · T1 {signal.targets?.t1 ?? '-'} · Stop {signal.stop_loss ?? '-'}</p>
            <ul className="mt-2 text-xs text-zinc-300 list-disc list-inside">
              {(signal.reasoning || []).slice(0, 3).map((r) => <li key={r}>{r}</li>)}
            </ul>
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={() => approve.mutate(signal.id)} disabled={!signal.id}>Take Trade</Button>
              <Button size="sm" variant="ghost" onClick={() => reject.mutate(signal.id)} disabled={!signal.id}>Pass</Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
