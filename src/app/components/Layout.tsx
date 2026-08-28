import { Outlet, useNavigate, useLocation } from 'react-router';
import { Search, Clock, Settings } from 'lucide-react';
import { useIsPWA } from '../hooks/useIsPWA';
import { Footer } from './Footer';
import { DisclaimerModal } from './DisclaimerModal';

export function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const isPWA = useIsPWA();

  const tabs = [
    {
      id: 'audit',
      label: '首頁審計',
      path: '/analyzer',
      icon: Search
    },
    {
      id: 'history',
      label: '歷史紀錄',
      path: '/history',
      icon: Clock
    },
    {
      id: 'settings',
      label: '金鑰設定',
      path: '/settings',
      icon: Settings
    }
  ];

  return (
    <div className="flex flex-col h-[100dvh] bg-background font-sans overflow-hidden">
      <DisclaimerModal />
      {/* Content Viewport */}
      <div className="flex-1 overflow-y-auto">
        <Outlet />
        {!isPWA && <Footer />}
      </div>

      {/* Fixed Bottom Navigation (Mobile PWA Tab Bar) */}
      {isPWA && (
        <nav className="bg-surface-1/95 backdrop-blur-md border-t border-hairline px-4 py-2 pb-safe flex items-center justify-around shrink-0">
          {tabs.map((tab) => {
            const isActive = location.pathname === tab.path;
            const Icon = tab.icon;

            return (
              <button
                key={tab.id}
                onClick={() => navigate(tab.path)}
                className={`flex flex-col items-center gap-1 py-1.5 px-4 rounded-lg transition-all cursor-pointer ${
                  isActive
                    ? 'bg-primary/15 text-primary'
                    : 'text-ink-subtle hover:text-ink-muted'
                }`}
              >
                <Icon className="w-5 h-5" />
                <span className="text-[10px] font-medium tracking-tight">
                  {tab.label}
                </span>
              </button>
            );
          })}
        </nav>
      )}
    </div>
  );
}
