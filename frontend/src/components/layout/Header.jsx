import { useQuery } from '@tanstack/react-query';
import { getAccountState } from '../../api/client';
import Badge from '../ui/Badge';
import { useHealth } from '../../hooks/useHealth';

export default function Header() {
  const { connected } = useHealth();
  const { data } = useQuery({ queryKey: ['account-state'], queryFn: getAccountState, refetchInterval: 30_000 });

  return (
    <header className="h-14 bg-zinc-900 border-b border-zinc-800 px-6 flex items-center justify-between">
      <h1 className="text-zinc-50 text-base font-medium">ICT Mission Control</h1>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-xs text-zinc-300">
          <span className={`inline-flex w-2 h-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
        <div className="font-mono text-sm text-zinc-200">${Number(data?.equity ?? 0).toLocaleString()}</div>
        <Badge variant="agent">{data?.status ?? 'paper'}</Badge>
      </div>
    </header>
  );
}
