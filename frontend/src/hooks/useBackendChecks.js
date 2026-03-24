import { useQuery } from '@tanstack/react-query';
import {
  getHealth,
  getAllPrices,
  getPositions,
  getSignals,
  getDRM,
} from '../api/client';

const CHECKS = [
  {
    key: 'health',
    label: 'Health endpoint',
    run: async () => {
      const data = await getHealth();
      return data?.status ? `status: ${data.status}` : 'ok';
    },
  },
  {
    key: 'prices',
    label: 'Live prices',
    run: async () => {
      const data = await getAllPrices();
      const count = Array.isArray(data) ? data.length : Object.keys(data || {}).length;
      if (!count) throw new Error('no symbols returned');
      return `${count} symbols`;
    },
  },
  {
    key: 'positions',
    label: 'Positions feed',
    run: async () => {
      const data = await getPositions();
      const list = Array.isArray(data) ? data : data?.positions || [];
      return `${list.length} open positions`;
    },
  },
  {
    key: 'signals',
    label: 'Signal stream',
    run: async () => {
      const data = await getSignals();
      const list = Array.isArray(data) ? data : data?.signals || [];
      return `${list.length} signals available`;
    },
  },
  {
    key: 'drm',
    label: 'DRM analyzer',
    run: async () => {
      const data = await getDRM('BTCUSD');
      if (!data) throw new Error('empty DRM response');
      return data?.symbol ? `symbol: ${data.symbol}` : 'response received';
    },
  },
];

export function useBackendChecks() {
  return useQuery({
    queryKey: ['backend-checks'],
    queryFn: async () => {
      const results = await Promise.all(
        CHECKS.map(async (check) => {
          try {
            const detail = await check.run();
            return { ...check, status: 'pass', detail };
          } catch (error) {
            return { ...check, status: 'fail', detail: error.message || 'failed' };
          }
        }),
      );

      return {
        checks: results,
        failed: results.filter((item) => item.status === 'fail').length,
        passed: results.filter((item) => item.status === 'pass').length,
        total: results.length,
      };
    },
    refetchInterval: 45_000,
  });
}
