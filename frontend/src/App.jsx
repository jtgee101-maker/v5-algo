import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/layout/AppShell';
import Charts from './pages/Charts';
import DRM from './pages/DRM';
import Dashboard from './pages/Dashboard';
import Journal from './pages/Journal';
import News from './pages/News';
import Performance from './pages/Performance';
import Positions from './pages/Positions';
import Reasoning from './pages/Reasoning';
import Research from './pages/Research';
import Risk from './pages/Risk';
import Scanner from './pages/Scanner';
import Settings from './pages/Settings';
import Signals from './pages/Signals';
import BuildProgress from './pages/BuildProgress';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
    mutations: {
      retry: 0,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/drm" element={<DRM />} />
            <Route path="/charts" element={<Charts />} />
            <Route path="/scanner" element={<Scanner />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/journal" element={<Journal />} />
            <Route path="/news" element={<News />} />
            <Route path="/research" element={<Research />} />
            <Route path="/research/:symbol" element={<Research />} />
            <Route path="/reasoning" element={<Reasoning />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/risk" element={<Risk />} />
            <Route path="/build-progress" element={<BuildProgress />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
