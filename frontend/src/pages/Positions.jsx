import { useQuery } from '@tanstack/react-query';
import { getDailyReview, getPositions, getStreak } from '../api/client';
import PositionCard from '../components/positions/PositionCard';
import Card from '../components/ui/Card';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/PageState';

export default function Positions() {
  const positions = useQuery({ queryKey: ['positions-page'], queryFn: getPositions, refetchInterval: 30_000 });
  const daily = useQuery({ queryKey: ['daily-review'], queryFn: getDailyReview, refetchInterval: 60_000 });
  const streak = useQuery({ queryKey: ['streak'], queryFn: getStreak, refetchInterval: 60_000 });

  if (positions.isLoading) return <LoadingState message="Loading positions..." />;
  if (positions.error) return <ErrorState message="Unable to load positions." onRetry={positions.refetch} />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card><p className="text-zinc-400 text-sm">Daily P&L</p><p className="font-mono text-2xl">{daily.data?.daily_pnl ?? '-'}</p></Card>
        <Card><p className="text-zinc-400 text-sm">Win Rate</p><p className="font-mono text-2xl">{daily.data?.win_rate ?? '-'}%</p></Card>
        <Card><p className="text-zinc-400 text-sm">Current Streak</p><p className="font-mono text-2xl">{streak.data?.current_streak ?? '-'}</p></Card>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {(positions.data?.positions || []).map((p, i) => <PositionCard key={i} position={p} />)}
      </div>
      {(positions.data?.positions || []).length === 0 ? <EmptyState message="No open positions." /> : null}
    </div>
  );
}
