import { motion } from 'framer-motion';
import {
  BarChart3,
  BookOpen,
  Brain,
  CandlestickChart,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  Newspaper,
  Search,
  Settings,
  Shield,
  TrendingUp,
  Wallet,
  Zap,
} from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getSignals } from '../../api/client';
import { useAppStore } from '../../store/appStore';

const NAV = [
  { section: 'MARKETS', items: [
    { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/drm', icon: FlaskConical, label: 'DRM Analysis', accent: 'purple' },
    { path: '/charts', icon: CandlestickChart, label: 'Charts' },
    { path: '/scanner', icon: Search, label: 'Scanner' },
  ]},
  { section: 'TRADING', items: [
    { path: '/signals', icon: Zap, label: 'Signals', badge: true },
    { path: '/positions', icon: Wallet, label: 'Positions' },
    { path: '/journal', icon: BookOpen, label: 'Journal' },
  ]},
  { section: 'RESEARCH', items: [
    { path: '/news', icon: Newspaper, label: 'News' },
    { path: '/research', icon: BarChart3, label: 'Research' },
    { path: '/reasoning', icon: Brain, label: 'Reasoning' },
  ]},
  { section: 'SYSTEM', items: [
    { path: '/performance', icon: TrendingUp, label: 'Performance' },
    { path: '/risk', icon: Shield, label: 'Risk' },
    { path: '/build-progress', icon: ListChecks, label: 'Build Progress' },
    { path: '/settings', icon: Settings, label: 'Settings' },
  ]},
];

export default function Sidebar() {
  const location = useLocation();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);
  const { data: signalsData } = useQuery({ queryKey: ['signals', 'sidebar'], queryFn: getSignals, refetchInterval: 10_000 });
  const signalList = Array.isArray(signalsData) ? signalsData : signalsData?.signals || [];
  const pendingCount = signalList.filter((s) => `${s.status || ''}`.toLowerCase().includes('pending')).length;

  return (
    <motion.aside
      animate={{ width: sidebarOpen ? 240 : 64 }}
      transition={{ duration: 0.2 }}
      className="border-r border-zinc-800 bg-zinc-900 h-screen sticky top-0 overflow-y-auto"
    >
      <div className="h-14 px-4 flex items-center font-semibold">{sidebarOpen ? 'ICT' : 'I'}</div>
      <nav className="px-2 pb-4">
        {NAV.map((group) => (
          <div key={group.section} className="mb-4">
            {sidebarOpen ? <p className="text-[10px] text-zinc-500 px-2 mb-1">{group.section}</p> : null}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = location.pathname === item.path || (item.path === '/research' && location.pathname.startsWith('/research/'));
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  title={!sidebarOpen ? item.label : ''}
                  className={`flex items-center justify-between gap-2 px-2 py-2 rounded-md text-sm mb-1 border-l-3 ${active ? 'border-l-blue-500 bg-zinc-800/80' : 'border-l-transparent hover:bg-zinc-800/50'}`}
                >
                  <span className="flex items-center gap-3">
                    <Icon size={16} />
                    {sidebarOpen ? <span>{item.label}</span> : null}
                  </span>
                  {item.badge && pendingCount > 0 && sidebarOpen ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-300">{pendingCount}</span>
                  ) : null}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <button
        className="m-2 w-[calc(100%-1rem)] rounded-md border border-zinc-700 text-sm py-2 hover:bg-zinc-800"
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        {sidebarOpen ? 'Collapse' : 'Expand'}
      </button>
    </motion.aside>
  );
}
