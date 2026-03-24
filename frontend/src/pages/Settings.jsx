import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { API_URL, brokerTest, getConfig, getHealth, killSwitch, setMode } from '../api/client';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';

export default function Settings() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ['settings-health'], queryFn: getHealth, refetchInterval: 30_000 });
  const config = useQuery({ queryKey: ['settings-config'], queryFn: getConfig, refetchInterval: 30_000 });
  const mode = useMutation({ mutationFn: (m) => setMode(m), onSuccess: () => qc.invalidateQueries({ queryKey: ['settings-config'] }) });
  const kill = useMutation({ mutationFn: killSwitch });
  const broker = useMutation({ mutationFn: brokerTest });

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-xl font-semibold mb-2">System</h2>
        <p className="text-sm">API Base: {API_URL}</p>
        <p className="text-sm">Health: {health.data?.status || 'unknown'}</p>
        <p className="text-sm">Mode: {config.data?.mode || 'paper'}</p>
        <a href={`${API_URL.replace('/api', '')}/docs`} target="_blank" rel="noreferrer" className="text-sm text-blue-300 underline mt-2 inline-block">Open Backend API Docs</a>
        <p className="text-sm text-zinc-400 mt-2">
          Need the step-by-step frontend rollout? Open{' '}
          <Link className="text-blue-300 underline" to="/build-progress">Build Progress</Link>.
        </p>
      </Card>
      <Card className="flex flex-wrap gap-2">
        <Button onClick={() => mode.mutate('paper')} loading={mode.isPending}>Set Paper</Button>
        <Button variant="ghost" onClick={() => mode.mutate('live')} loading={mode.isPending}>Set Live</Button>
        <Button variant="ghost" onClick={() => broker.mutate()} loading={broker.isPending}>Broker Test</Button>
        <Button variant="danger" onClick={() => kill.mutate()} loading={kill.isPending}>Kill Switch</Button>
      </Card>
      {broker.data ? <Card><pre className="text-xs overflow-auto">{JSON.stringify(broker.data, null, 2)}</pre></Card> : null}
    </div>
  );
}
