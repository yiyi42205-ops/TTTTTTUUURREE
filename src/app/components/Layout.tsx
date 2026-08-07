import { Outlet, useNavigate, useLocation } from 'react-router';
import { Search, Clock, Settings } from 'lucide-react';
import { useEffect, useState } from 'react';

export function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [isPWA, setIsPWA] = useState(false);

  useEffect(() => {
    const checkPWA = window.matchMedia('(display-mode: standalone)').matches 
                  || (window.navigator as any).standalone === true
                  || window.matchMedia('(max-width: 767px)').matches;
    setIsPWA(checkPWA);
  }, []);

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
    <div className="flex flex-col h-screen bg-[#f5f1e8] font-sans overflow-hidden">
      {/* Content Viewport */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <Outlet />
      </div>

      {/* Fixed Bottom Navigation (Mobile PWA Tab Bar) */}
      {isPWA && (
        <nav className="fixed bottom-0 left-0 right-0 z-50 bg-[#f5f1e8]/90 backdrop-blur-md border-t-3 border-[#4a5d52] px-4 py-2 pb-safe flex items-center justify-around shadow-[0_-4px_0_0_rgba(74,93,82,0.05)]">
          {tabs.map((tab) => {
            const isActive = location.pathname === tab.path;
            const Icon = tab.icon;

            return (
              <button
                key={tab.id}
                onClick={() => navigate(tab.path)}
                className={`flex flex-col items-center gap-1 py-1 px-4 rounded-xl transition-all cursor-pointer ${
                  isActive
                    ? 'bg-[#6b8e7f] text-white border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52]'
                    : 'text-[#6b8e7f] border-2 border-transparent'
                }`}
              >
                <Icon className="w-5.5 h-5.5 stroke-[2.5]" />
                <span className="text-[10px] font-black font-display tracking-tight">
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
