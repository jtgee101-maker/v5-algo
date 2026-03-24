import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getScratchpadDetail, getScratchpadSessions } from '../api/client';
import Card from '../components/ui/Card';
import { ErrorState, LoadingState } from '../components/ui/PageState';

export default function Reasoning() {
  const sessions = useQuery({ queryKey: ['scratch-sessions'], queryFn: () => getScratchpadSessions(20) });
  const [selected, setSelected] = useState(null);
  const detail = useQuery({ queryKey: ['scratch-detail', selected], queryFn: () => getScratchpadDetail(selected), enabled: Boolean(selected) });

  if (sessions.isLoading) return <LoadingState message="Loading scratchpad sessions..." />;
  if (sessions.error) return <ErrorState message="Unable to load scratchpad sessions." onRetry={sessions.refetch} />;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-1">
        <h3 className="font-semibold mb-2">Sessions</h3>
        <div className="space-y-2">
          {(sessions.data?.sessions || []).map((s) => (
            <button key={s.session_id} onClick={() => setSelected(s.session_id)} className="w-full text-left border border-zinc-700 rounded p-2 hover:bg-zinc-800">
              <p className="text-sm font-mono">{s.session_id}</p>
              <p className="text-xs text-zinc-500">{s.entries} entries</p>
            </button>
          ))}
        </div>
      </Card>
      <Card className="lg:col-span-2">
        <h3 className="font-semibold mb-2">Timeline</h3>
        {(detail.data?.entries || []).map((e, i) => <p key={i} className="text-sm text-zinc-300 border-b border-zinc-800 py-2">{e.type} · {e.ts}</p>)}
      </Card>
    </div>
  );
}
