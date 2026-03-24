import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getSafetyStatus, resetBreaker } from '../api/client';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';

export default function Risk() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ['safety'], queryFn: getSafetyStatus, refetchInterval: 30_000 });
  const reset = useMutation({ mutationFn: resetBreaker, onSuccess: () => qc.invalidateQueries({ queryKey: ['safety'] }) });

  if (isLoading) return <Card>Loading safety state...</Card>;
  if (error) return <Card>Unable to load safety status.</Card>;

  return (
    <Card>
      <h2 className="text-xl font-semibold mb-2">Risk Controls</h2>
      <p className="text-sm">Circuit Breaker: {data?.circuit_breaker?.tripped ? 'TRIPPED' : 'OK'}</p>
      <p className="text-sm">Consecutive Losses: {data?.circuit_breaker?.consecutive_losses ?? 0}</p>
      <p className="text-sm">Cooldowns: {Object.keys(data?.trade_cooldown?.active_cooldowns || {}).length}</p>
      <Button className="mt-3" onClick={() => reset.mutate()} loading={reset.isPending}>Reset Breaker</Button>
      {reset.isSuccess ? <p className="text-xs text-emerald-400 mt-2">Breaker reset request sent.</p> : null}
    </Card>
  );
}
