import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { getDRM, getSymbolDetail } from '../api/client';
import Card from '../components/ui/Card';

export default function Research() {
  const { symbol = 'USOIL' } = useParams();
  const detail = useQuery({ queryKey: ['detail', symbol], queryFn: () => getSymbolDetail(symbol), refetchInterval: 45_000 });
  const drm = useQuery({ queryKey: ['research-drm', symbol], queryFn: () => getDRM(symbol), refetchInterval: 60_000 });

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-xl font-semibold">Research · {symbol}</h2>
        <p className="text-sm text-zinc-400 mt-2">Price: {detail.data?.price || detail.data?.current_price || '-'}</p>
      </Card>
      <Card>
        <h3 className="font-semibold mb-2">DRM Summary</h3>
        <p className="text-sm text-zinc-400">ATR: {drm.data?.atr ?? '-'} · Unfilled FVGs: {drm.data?.unfilled_fvgs ?? '-'}</p>
      </Card>
    </div>
  );
}
