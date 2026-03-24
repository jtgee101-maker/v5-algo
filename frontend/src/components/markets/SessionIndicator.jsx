import Badge from '../ui/Badge';

export default function SessionIndicator({ active, label = 'Unknown', type = 'market' }) {
  return <Badge variant={active ? 'live' : 'closed'}>{active ? `LIVE · ${label}` : `CLOSED · ${type}`}</Badge>;
}
