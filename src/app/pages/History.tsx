import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { historyStore, HistoryEntry } from '../utils/historyStore';
import { Clock, Shield, Star, Trash2, Calendar, FileText, ChevronRight, CheckSquare, Square, RefreshCw } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export function History() {
  const navigate = useNavigate();
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [isEditMode, setIsEditMode] = useState(false);
  const [selectedStores, setSelectedStores] = useState<Set<string>>(new Set());

  useEffect(() => {
    setHistory(historyStore.getHistory());
  }, []);

  const formatDate = (timestamp: number) => {
    const date = new Date(timestamp);
    return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  };

  const handleCardClick = (entry: HistoryEntry) => {
    if (isEditMode) {
      toggleSelectStore(entry.storeName);
      return;
    }
    // Load result directly without re-triggering API calls
    navigate('/results', { 
      state: { 
        cachedShopResults: [entry.stats],
        storeIds: [entry.storeName]
      } 
    });
  };

  const toggleSelectStore = (storeName: string) => {
    const next = new Set(selectedStores);
    if (next.has(storeName)) {
      next.delete(storeName);
    } else {
      next.add(storeName);
    }
    setSelectedStores(next);
  };

  const handleDeleteSelected = () => {
    if (selectedStores.size === 0) return;
    
    if (confirm(`確定要刪除選取的 ${selectedStores.size} 筆分析紀錄嗎？`)) {
      selectedStores.forEach(name => {
        historyStore.deleteHistory(name);
      });
      // Refresh list
      const updated = historyStore.getHistory();
      setHistory(updated);
      setSelectedStores(new Set());
      setIsEditMode(false);
    }
  };

  const handleClearAll = () => {
    if (confirm('警告：確定要清空所有的歷史分析紀錄嗎？這項動作無法復原。')) {
      historyStore.clearHistory();
      setHistory([]);
      setSelectedStores(new Set());
      setIsEditMode(false);
    }
  };

  const toggleSelectAll = () => {
    if (selectedStores.size === history.length) {
      setSelectedStores(new Set());
    } else {
      setSelectedStores(new Set(history.map(e => e.storeName)));
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#f5f1e8] p-4 md:p-8 pb-24">
      <div className="max-w-xl mx-auto">
        {/* Header Block */}
        <div className="flex flex-col sm:flex-row justify-between items-center gap-4 mb-8">
          <div className="text-center sm:text-left">
            <h1 className="text-3xl font-black text-[#4a5d52] font-display tracking-tight mb-2 flex items-center justify-center sm:justify-start gap-2">
              歷史紀錄
            </h1>
            <p className="text-sm text-[#6b8e7f] font-medium">
              本機快取的審計結果，隨時可離線載入查看。
            </p>
          </div>
          
          {history.length > 0 && (
            <div className="flex gap-2 shrink-0">
              <button
                onClick={() => {
                  setIsEditMode(!isEditMode);
                  setSelectedStores(new Set());
                }}
                className={`px-4 py-2 rounded-xl text-xs font-black border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] transition-all cursor-pointer font-display ${
                  isEditMode ? 'bg-[#e8c547] text-[#4a5d52]' : 'bg-white text-[#4a5d52]'
                }`}
              >
                {isEditMode ? '取消選取' : '編輯歷史'}
              </button>
              {isEditMode && selectedStores.size > 0 && (
                <button
                  onClick={handleDeleteSelected}
                  className="bg-[#ef4444] text-white px-4 py-2 rounded-xl text-xs font-black border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] flex items-center gap-1.5 cursor-pointer font-display"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  刪除 ({selectedStores.size})
                </button>
              )}
            </div>
          )}
        </div>

        {/* List Content */}
        {history.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-3xl border-3 border-[#4a5d52] shadow-tactile p-8">
            <div className="w-14 h-14 bg-[#6b8e7f]/10 border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] rounded-2xl flex items-center justify-center mb-5 text-[#6b8e7f] mx-auto">
              <Clock className="w-7 h-7 stroke-[2.5]" />
            </div>
            <h3 className="text-lg font-black text-[#4a5d52] font-display mb-2">暫無歷史紀錄</h3>
            <p className="text-xs text-[#6b8e7f] leading-relaxed max-w-xs mx-auto font-medium">
              當您在首頁進行店家 Google Maps 評價審計後，完整的圖表與分析日誌將會自動儲存於此。
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {isEditMode && (
              <div className="flex justify-between items-center px-2 py-1 text-xs font-bold text-[#6b8e7f]">
                <button 
                  onClick={toggleSelectAll} 
                  className="flex items-center gap-1.5 hover:text-[#4a5d52] cursor-pointer"
                >
                  {selectedStores.size === history.length ? (
                    <CheckSquare className="w-4 h-4 text-[#6b8e7f]" />
                  ) : (
                    <Square className="w-4 h-4 text-[#6b8e7f]" />
                  )}
                  全選 ({history.length})
                </button>
                
                <button 
                  onClick={handleClearAll} 
                  className="text-[#ef4444] hover:underline cursor-pointer flex items-center gap-1"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  清空歷史
                </button>
              </div>
            )}

            <div className="space-y-3.5">
              <AnimatePresence>
                {history.map((entry) => {
                  const isSelected = selectedStores.has(entry.storeName);
                  const stats = entry.stats;
                  const scoreColor = stats.trustScore >= 70 ? 'text-[#6b8e7f]' : stats.trustScore >= 40 ? 'text-[#e8c547]' : 'text-[#ef4444]';
                  const scoreBg = stats.trustScore >= 70 ? 'bg-[#6b8e7f]/10 border-[#6b8e7f]/30' : stats.trustScore >= 40 ? 'bg-[#e8c547]/10 border-[#e8c547]/30' : 'bg-[#ef4444]/10 border-[#ef4444]/30';

                  return (
                    <motion.div
                      key={entry.storeName}
                      layout
                      exit={{ opacity: 0, x: -20 }}
                      onClick={() => handleCardClick(entry)}
                      className={`bg-white rounded-2xl border-2 border-[#4a5d52] shadow-tactile-sm hover:shadow-tactile hover:-translate-y-0.5 transition-all duration-200 p-5 flex items-center gap-4 cursor-pointer select-none ${
                        isSelected ? 'bg-amber-50/40 border-[#e8c547]' : ''
                      }`}
                    >
                      {isEditMode && (
                        <div className="shrink-0 text-[#4a5d52]">
                          {isSelected ? (
                            <CheckSquare className="w-5 h-5 text-[#e8c547] fill-[#e8c547]/10" />
                          ) : (
                            <Square className="w-5 h-5 text-[#6b8e7f]" />
                          )}
                        </div>
                      )}

                      <div className="flex-1 min-w-0">
                        {/* Meta time */}
                        <div className="flex items-center gap-1.5 text-[10px] text-[#6b8e7f] font-bold mb-1.5">
                          <Calendar className="w-3 h-3" />
                          <span>{formatDate(entry.timestamp)}</span>
                        </div>

                        {/* Title */}
                        <h3 className="text-base font-black text-[#4a5d52] truncate font-display mb-3">
                          {entry.storeName}
                        </h3>

                        {/* Score stats row */}
                        <div className="flex flex-wrap items-center gap-3">
                          {/* Trust score badge */}
                          <div className={`px-2 py-1 rounded-lg border text-[10px] font-black flex items-center gap-1 ${scoreBg} ${scoreColor}`}>
                            <Shield className="w-3 h-3" />
                            <span>信譽: {stats.trustScore}</span>
                          </div>

                          {/* Star Ratings comparison */}
                          <div className="flex items-center gap-2 text-xs font-bold text-[#4a5d52]">
                            <span className="text-gray-400 line-through flex items-center gap-0.5">
                              <Star className="w-3 h-3 fill-gray-300 stroke-gray-400" />
                              {stats.originalRating.toFixed(1)}
                            </span>
                            <ArrowRight className="w-3.5 h-3.5 text-gray-400" />
                            <span className="text-[#6b8e7f] flex items-center gap-0.5 font-black">
                              <Star className="w-3 h-3 fill-[#e8c547] stroke-[#e8c547]" />
                              {stats.filteredRating.toFixed(1)}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Right indicator arrow */}
                      {!isEditMode && (
                        <div className="shrink-0 text-gray-300">
                          <ChevronRight className="w-5 h-5" />
                        </div>
                      )}
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Arrow helper icon
function ArrowRight(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}
