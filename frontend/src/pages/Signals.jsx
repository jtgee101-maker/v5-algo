import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { approveSignal, getSignals, rejectSignal } from '../api/client';
import Button from '../components/ui/Button';
import SignalBrief from '../components/signals/SignalBrief';
import SignalDetail from '../components/signals/SignalDetail';

const TABS = ['all', 'pending', 'taken', 'passed'];

export default function Signals() {
  const qc = useQueryClient();
  const { data, isLoading, refetch } = useQuery({ queryKey: ['signals'], queryFn: getSignals, refetchInterval: 10_000 });
  const [tab, setTab] = useState('all');
  const [selected, setSelected] = useState(null);

  const list = Array.isArray(data) ? data : data?.signals || [];
  const filtered = useMemo(
    () => list.filter((s) => tab === 'all' || `${s.status || ''}`.toLowerCase().includes(tab)),
    [list, tab]
  );

  const approve = useMutation({ mutationFn: (s) => approveSignal(s.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['signals'] }) });
  const reject = useMutation({ mutationFn: (s) => rejectSignal(s.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['signals'] }) });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`px-3 py-1.5 rounded-full text-xs border ${tab === t ? 'bg-zinc-700 border-zinc-500' : 'border-zinc-700'}`}>
              {t.toUpperCase()}
            </button>
          ))}
        </div>
        <Button variant="ghost" size="sm" onClick={() => refetch()}>Refresh</Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-2 max-h-[70vh] overflow-auto pr-1">
          {isLoading ? <div className="card">Loading signals...</div> : null}
          {!isLoading && filtered.length === 0 ? <div className="card">No {tab} signals.</div> : null}
          {filtered.map((s) => <SignalBrief key={s.id || `${s.symbol}-${s.timestamp}`} signal={s} onSelect={() => setSelected(s)} />)}
        </div>
        <div className="lg:col-span-2">
          <SignalDetail signal={selected} onApprove={(s) => approve.mutate(s)} onReject={(s) => reject.mutate(s)} />
        </div>
      </div>
    </div>
  );
}
