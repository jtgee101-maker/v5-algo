import { useQuery } from '@tanstack/react-query';
import { getTradeJournal } from '../api/client';
import Card from '../components/ui/Card';

export default function Journal() {
  const { data } = useQuery({ queryKey: ['journal'], queryFn: getTradeJournal });
  return (
    <div className="space-y-3">
      {(data?.entries || []).map((e) => (
        <Card key={e.trade_id}>
          <p className="font-semibold">{e.symbol} · {e.result}</p>
          <p className="text-sm text-zinc-400">{e.strategy} · {e.signal}</p>
          <p className="text-sm mt-1">{e.notes}</p>
        </Card>
      ))}
    </div>
  );
}
