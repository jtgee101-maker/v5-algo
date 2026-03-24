import Button from './Button';
import Card from './Card';
import Skeleton from './Skeleton';

export function LoadingState({ message = 'Loading...' }) {
  return (
    <Card>
      <p className="text-sm text-zinc-400 mb-3">{message}</p>
      <Skeleton height="20px" />
    </Card>
  );
}

export function ErrorState({ message = 'Unable to load data.', onRetry }) {
  return (
    <Card>
      <p className="text-sm text-red-300 mb-3">{message}</p>
      {onRetry ? <Button variant="ghost" size="sm" onClick={onRetry}>Retry</Button> : null}
    </Card>
  );
}

export function EmptyState({ message = 'No data available.' }) {
  return (
    <Card>
      <p className="text-sm text-zinc-500">{message}</p>
    </Card>
  );
}
