import { useNavigate } from 'react-router-dom';
import Badge from '../ui/Badge';
import Card from '../ui/Card';
import PriceTag from '../ui/PriceTag';
import SessionIndicator from './SessionIndicator';

export default function SymbolCard({ symbol, price, change, session, type }) {
  const navigate = useNavigate();
  return (
    <Card hover onClick={() => navigate(`/research/${symbol}`)} className="cursor-pointer">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">{symbol}</h3>
        <Badge variant="neutral" size="sm">{type || 'asset'}</Badge>
      </div>
      <PriceTag value={price} change={change} size="lg" />
      <div className="mt-2 text-sm">
        <Badge variant={change >= 0 ? 'bullish' : 'bearish'}>{change?.toFixed(2)}%</Badge>
      </div>
      <div className="mt-3">
        <SessionIndicator active={session?.active} label={session?.label} type={session?.type} />
      </div>
    </Card>
  );
}
