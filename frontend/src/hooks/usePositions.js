import { useQuery } from '@tanstack/react-query';
import { getPositions } from '../api/client';

export function usePositions() {
  return useQuery({
    queryKey: ['positions'],
    queryFn: getPositions,
    refetchInterval: 30_000,
  });
}
