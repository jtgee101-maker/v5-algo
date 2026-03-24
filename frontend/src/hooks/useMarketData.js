import { useQuery } from '@tanstack/react-query';
import { getMarketOverview } from '../api/client';

export function useMarketData() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['market-overview'],
    queryFn: getMarketOverview,
    refetchInterval: 45_000,
  });

  return { data, isLoading, error, refetch };
}
