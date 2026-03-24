import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/client';

export function useHealth() {
  const query = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  return {
    ...query,
    connected: query.data?.status === 'ok',
  };
}
