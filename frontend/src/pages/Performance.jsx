import { useQuery } from '@tanstack/react-query';
import { getDailyReview, getStreak, getWeeklyReview } from '../api/client';
import Card from '../components/ui/Card';

export default function Performance() {
  const daily = useQuery({ queryKey: ['perf-daily'], queryFn: getDailyReview });
  const weekly = useQuery({ queryKey: ['perf-weekly'], queryFn: getWeeklyReview });
  const streak = useQuery({ queryKey: ['perf-streak'], queryFn: getStreak });

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card><p className="text-sm text-zinc-400">Daily P&L</p><p className="font-mono text-2xl">{daily.data?.daily_pnl ?? '-'}</p></Card>
      <Card><p className="text-sm text-zinc-400">Weekly</p><p className="font-mono text-2xl">{weekly.data?.weekly_pnl ?? '-'}</p></Card>
      <Card><p className="text-sm text-zinc-400">Streak</p><p className="font-mono text-2xl">{streak.data?.current_streak ?? '-'}</p></Card>
    </div>
  );
}
