import { Outlet } from 'react-router-dom';
import Header from './Header';
import PriceBanner from './PriceBanner';
import Sidebar from './Sidebar';

export default function AppShell() {
  return (
    <div className="flex min-h-screen bg-zinc-950 text-zinc-50">
      <Sidebar />
      <div className="flex-1 min-w-0">
        <Header />
        <PriceBanner />
        <main className="max-w-7xl mx-auto px-6 py-6 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
