import { useMutation, useQuery } from '@tanstack/react-query';
import { getDRM, scanDRM } from '../api/client';

export function useDRMAnalysis(symbol) {
  return useQuery({
    queryKey: ['drm-analysis', symbol],
    queryFn: () => getDRM(symbol),
    enabled: Boolean(symbol),
    refetchInterval: false,
  });
}

export function useDRMScan() {
  return useMutation({ mutationFn: scanDRM });
}
