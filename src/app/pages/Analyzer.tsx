import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate } from 'react-router';
import { ArrowLeft, Loader2, Link as LinkIcon, X, Search, Info, Plus, Globe, Sliders, Database, ShieldCheck, Sparkles, Shield, AlertTriangle, ClipboardPaste } from 'lucide-react';
import { useIsPWA } from '../hooks/useIsPWA';
import { RESTAURANTS_DATA, Restaurant } from '../data/restaurantsData';

export function Analyzer() {
  const navigate = useNavigate();
  const [urls, setUrls] = useState<string[]>(['', '', '']);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const isPWA = useIsPWA();
  
  // Suggestion Dropdown states for each slot
  const [activeSlot, setActiveSlot] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Custom Scraper states
  const [activeTab, setActiveTab] = useState<'preset' | 'scraper'>('preset');
  const [scrapeUrls, setScrapeUrls] = useState<string[]>(['', '', '']);
  const [maxReviews, setMaxReviews] = useState(50);
  const [scrapeLoadingStep, setScrapeLoadingStep] = useState('');
  const [scrapeError, setScrapeError] = useState('');

  // Manual Clipboard Paste for Google Maps URLs
  const handlePasteFromClipboard = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      const trimmed = (text || '').trim();
      const isGoogleMapsUrl = trimmed.startsWith('https://') && 
                             (trimmed.includes('google.com/maps') || 
                              trimmed.includes('maps.app.goo.gl') || 
                              trimmed.includes('/maps/') ||
                              trimmed.includes('g.page'));
      
      if (isGoogleMapsUrl) {
        if (scrapeUrls.includes(trimmed)) return;
        
        const newScrapeUrls = [...scrapeUrls];
        const emptyIndex = newScrapeUrls.findIndex(url => url === '');
        if (emptyIndex !== -1) {
           newScrapeUrls[emptyIndex] = trimmed;
        } else {
           newScrapeUrls[0] = trimmed;
        }
        setScrapeUrls(newScrapeUrls);
        setActiveTab('scraper');
      } else {
        alert('剪貼簿中未偵測到有效的 Google Maps 連結。');
      }
    } catch (err) {
      console.warn('Clipboard read permission denied or not supported:', err);
      alert('無法讀取剪貼簿，請確認瀏覽器授權。');
    }
  }, [scrapeUrls]);

  // Close dropdown on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setActiveSlot(null);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleUrlChange = (index: number, value: string) => {
    const trimmed = value.trim();
    const isUrl = trimmed.startsWith('http://') || 
                  trimmed.startsWith('https://') || 
                  trimmed.includes('google.com') || 
                  trimmed.includes('maps.app.goo.gl') || 
                  trimmed.includes('/maps/');
    if (isUrl) {
      alert("內建測試數據庫僅支援搜尋與點選內建店家（例如：小高拉麵、清心師大）。\n如果您想輸入 Google Maps 網址進行即時爬取，請點選上方切換至「Google Maps 即時爬取」分頁。");
      return;
    }

    const newUrls = [...urls];
    newUrls[index] = value;
    setUrls(newUrls);
    
    // Open suggestions for this slot and set query
    setActiveSlot(index);
    setSearchQuery(value);
  };

  const handleSelectRestaurant = (slotIndex: number, restaurant: Restaurant) => {
    const newUrls = [...urls];
    newUrls[slotIndex] = restaurant.name;
    setUrls(newUrls);
    setActiveSlot(null);
    setSearchQuery('');
  };

  const handleClear = (index: number) => {
    const newUrls = [...urls];
    newUrls[index] = '';
    setUrls(newUrls);
  };

  const handleScrapeUrlChange = (index: number, value: string) => {
    const newUrls = [...scrapeUrls];
    newUrls[index] = value;
    setScrapeUrls(newUrls);
  };

  const handleScrapeUrlClear = (index: number) => {
    const newUrls = [...scrapeUrls];
    newUrls[index] = '';
    setScrapeUrls(newUrls);
  };

  const handleAddPreset = (restaurant: Restaurant) => {
    // Find the first empty slot
    const emptyIndex = urls.findIndex(url => url.trim() === '');
    if (emptyIndex !== -1) {
      const newUrls = [...urls];
      newUrls[emptyIndex] = restaurant.name;
      setUrls(newUrls);
    } else {
      // If all full, replace the first one
      const newUrls = [...urls];
      newUrls[0] = restaurant.name;
      setUrls(newUrls);
    }
  };

  const handleAnalyze = () => {
    const filledUrls = urls.filter(url => url.trim() !== '');
    if (filledUrls.length === 0) return;

    // Smart Match logic from inputs to local DB IDs
    const matchedStoreIds = urls.map(input => {
      const trimmed = input.trim().toLowerCase();
      if (!trimmed) return null;

      // 1. Direct Name Match
      let matched = RESTAURANTS_DATA.find(r => r.name.toLowerCase() === trimmed);
      if (matched) return matched.id;

      // 2. Keyword check
      matched = RESTAURANTS_DATA.find(r => trimmed.includes(r.name.toLowerCase()));
      if (matched) return matched.id;

      // 3. Substring match
      matched = RESTAURANTS_DATA.find(r => r.name.toLowerCase().includes(trimmed) || trimmed.includes(r.name.toLowerCase()));
      if (matched) return matched.id;

      // 4. Specific keyword mappings for raw Google Map URLs
      const keywordMappings: { [key: string]: string } = {
        '長樂': 'ramen_washed_3',
        '好假': 'ramen_washed_1',
        '好呷': 'ramen_washed_2',
        '十二巷': 'ramen_clean_1',
        '小高': 'ramen_clean_2',
        '隱家': 'ramen_clean_3',
        '城市盒子': 'bento_washed_1',
        '村民': 'bento_washed_2',
        '米泰豐': 'bento_washed_3',
        'lulu': 'bento_clean_1',
        '餵': 'bento_clean_2',
        '龍城': 'bento_clean_3',
        '深夜': 'drink_washed_1',
        '發發': 'drink_washed_2',
        '茶沐': 'drink_washed_3',
        '可不可': 'drink_clean_1',
        '清心': 'drink_clean_2',
        '迷客夏': 'drink_clean_3'
      };

      for (const key in keywordMappings) {
        if (trimmed.includes(key)) {
          return keywordMappings[key];
        }
      }

      // Default fallback
      return null;
    }).filter(Boolean) as string[];

    if (matchedStoreIds.length === 0) {
      const fallbackIds = filledUrls.map((_, i) => RESTAURANTS_DATA[i].id);
      setIsAnalyzing(true);
      setTimeout(() => {
        navigate('/results', { state: { storeIds: fallbackIds } });
      }, 1500);
      return;
    }

    setIsAnalyzing(true);

    setTimeout(() => {
      navigate('/results', { state: { storeIds: matchedStoreIds } });
    }, 1800);
  };
  
  const handleScrapeAndAnalyze = async () => {
    const activeUrls = scrapeUrls.map(u => u.trim()).filter(Boolean);
    if (activeUrls.length === 0) return;
    
    // Validate each active URL/place name format
    for (const url of activeUrls) {
      const isUrl = url.startsWith('http://') || url.startsWith('https://');
      if (isUrl) {
        const isGoogleMaps = (url.includes('google.') && url.includes('/maps/')) || url.includes('maps.app.goo.gl');
        if (!isGoogleMaps) {
          alert(`網址格式錯誤: "${url}" 不是正確的 Google Maps 商家網址 (例如包含 google.com/maps 或 maps.app.goo.gl)。`);
          return;
        }
      }
    }
    
    setScrapeError('');
    setIsAnalyzing(true);
    setScrapeLoadingStep(`正在平行抓取 ${activeUrls.length} 間店家的評論...`);

    const steps = [
      '正在向 Apify 送出抓取請求（若失敗將自動改用本地 Playwright 備援）...',
      '正在解析評論文字、發布時間與打卡照片...',
      '正在整理資料格式...'
    ];
    let stepIdx = 0;
    const interval = setInterval(() => {
      if (stepIdx < steps.length) {
        setScrapeLoadingStep(steps[stepIdx]);
        stepIdx++;
      }
    }, 4000);

    try {
      const promises = activeUrls.map(async (currentUrl, i) => {
        let storeName = currentUrl;
        if (currentUrl.startsWith('http://') || currentUrl.startsWith('https://')) {
          try {
            const match = currentUrl.match(/\/place\/([^\/]+)/);
            if (match && match[1]) {
              storeName = decodeURIComponent(match[1].replace(/\+/g, ' '));
            } else {
              storeName = `自定義店家 ${i + 1}`;
            }
          } catch (e) {
            storeName = `自定義店家 ${i + 1}`;
          }
        }

        try {
          const response = await fetch('/api/scrape', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              url: currentUrl,
              maxReviews: maxReviews
            })
          });

          const data = await response.json().catch(() => null);

          if (!response.ok) {
            throw new Error(data?.error || '伺服器爬取失敗，請確認本地爬蟲伺服器已開啟，且網址正確。');
          }

          if (!data?.reviews || data.reviews.length === 0) {
            throw new Error('無法抓取到任何評論，可能是網址無效或 Google 正在阻擋爬蟲請求。');
          }

          // /api/scrape now always returns reviews normalized to a single shape
          // (username/stars/time/text/images), regardless of whether Apify,
          // the Playwright fallback, or the cache actually served the request.
          const mappedReviews = data.reviews.map((item: any) => ({
            username: item.username || '未知用戶',
            stars: parseInt(item.stars, 10) || 5,
            time: item.time || '',
            text: item.text || '',
            images: Array.isArray(item.images) ? item.images : []
          }));

          return {
            id: `custom_scraped_shop_${i}`,
            name: storeName,
            reviews: mappedReviews,
            metadata: data.metadata || {}
          };
        } catch (e: any) {
          throw new Error(`[${storeName}] 爬取失敗: ${e.message || '請確認本地後端服務已開啟'}`);
        }
      });

      const customShops = await Promise.all(promises);

      navigate('/results', {
        state: {
          storeIds: [],
          customShops: customShops
        }
      });
    } catch (e: any) {
      console.error(e);
      setScrapeError(e.message || '爬取過程中發生未知錯誤，請確認本地爬蟲伺服器已開啟。');
    } finally {
      // Always clear the progress-message interval and reset loading state,
      // whether the scrape succeeded, failed, or the response was a 500 —
      // previously this was only cleared on the success path, so a failed
      // scrape left the interval running in the background indefinitely.
      clearInterval(interval);
      setIsAnalyzing(false);
      setScrapeLoadingStep('');
    }
  };

  const filledCount = urls.filter(url => url.trim() !== '').length;
  const matchedCount = urls.filter(url => RESTAURANTS_DATA.some(r => r.name === url)).length;
  const filledScrapeCount = scrapeUrls.filter(url => url.trim() !== '').length;

  const filteredSuggestions = searchQuery.trim() === ''
    ? []
    : RESTAURANTS_DATA.filter(r =>
        r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        r.categoryLabel.includes(searchQuery)
      );

  const ramenPresets = RESTAURANTS_DATA.filter(r => r.category === 'ramen').slice(0, 4);
  const bentoPresets = RESTAURANTS_DATA.filter(r => r.category === 'bento').slice(0, 4);
  const drinkPresets = RESTAURANTS_DATA.filter(r => r.category === 'drinks').slice(0, 4);

  return (
    <div className="min-h-screen bg-[#f5f1e8] font-sans selection:bg-[#6b8e7f]/20 pb-12">
      {/* Brand Navigation Header */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-[#f5f1e8]/80 border-b border-[#d4c5b0]/30 px-4 md:px-8 py-3.5 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
          <div className="bg-[#6b8e7f] text-white w-9 h-9 rounded-xl border-2 border-[#4a5d52] font-black text-base shadow-sm flex items-center justify-center">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <span className="font-display font-black text-lg text-[#4a5d52] tracking-tight">
            疑騙真星 <span className="text-[#6b8e7f] font-sans font-bold text-sm bg-white border border-[#d4c5b0]/60 px-1.5 py-0.5 rounded-md ml-1">TrueRating</span>
          </span>
        </div>
        {!isPWA && (
          <motion.button
            onClick={() => navigate('/')}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="flex items-center gap-1.5 bg-white px-4 py-1.5 rounded-full shadow-xs border border-[#d4c5b0] text-xs font-bold text-[#4a5d52] cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4 text-[#6b8e7f]" />
            返回首頁
          </motion.button>
        )}
      </header>

      <div className="container mx-auto px-4 py-8 max-w-4xl">


        {/* Info Banner */}
        {!isPWA && (
          <motion.div
            initial={{ opacity: 0, y: -15 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white/95 backdrop-blur-xs rounded-2xl p-4.5 mb-8 shadow-xs border border-[#e8c547]/40 flex items-start gap-3.5"
          >
            <Info className="w-5 h-5 text-[#e8c547] shrink-0 mt-0.5" />
            <div className="text-xs md:text-sm text-[#4a5d52] leading-relaxed">
              <span className="font-extrabold text-[#8b7534] bg-[#e8c547]/20 px-1.5 py-0.5 rounded mr-1">測試數據庫已加載</span>
              系統內建拉麵、手搖飲、健康餐等 18 間店家真實歷史評論。您可以直接在對比欄位搜尋，或從下方推薦庫快速加載店家進行多店「濾水」對照！
            </div>
          </motion.div>
        )}

        {/* Main Analysis Dashboard Box */}
        <div className="relative w-full max-w-3xl mx-auto mb-8">
          <div className="bg-white rounded-[32px] shadow-md p-6 md:p-8 border-2 border-[#d4c5b0]/60">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-center mb-8"
            >
              <div className="text-3xl mb-1 text-[#e8c547] select-none tracking-widest">★☆★☆★</div>
              <h1 className="text-xl md:text-2xl font-black text-[#4a5d52] font-display">
                真實口碑評價對比分析儀
              </h1>
              <p className="text-xs text-[#6b8e7f] mt-1 font-medium">
                選擇下方店家測試數據集，或透過即時爬蟲抓取 Google Map 上最新資料
              </p>
            </motion.div>

            {/* Segmented Tab Selectors */}
            <div className="flex gap-2 p-1.5 bg-[#f5f1e8] rounded-2xl mb-8 border-2 border-[#4a5d52] shadow-tactile-sm">
              <button
                onClick={() => setActiveTab('preset')}
                className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs md:text-sm font-black transition-all cursor-pointer ${
                  activeTab === 'preset'
                    ? 'bg-white text-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] border-2 border-[#4a5d52]'
                    : 'text-[#6b8e7f] hover:text-[#4a5d52] border-2 border-transparent hover:bg-white/50'
                }`}
              >
                <Database className="w-4 h-4" />
                內建測試數據庫
              </button>
              <button
                onClick={() => setActiveTab('scraper')}
                className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs md:text-sm font-black transition-all cursor-pointer ${
                  activeTab === 'scraper'
                    ? 'bg-white text-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] border-2 border-[#4a5d52]'
                    : 'text-[#6b8e7f] hover:text-[#4a5d52] border-2 border-transparent hover:bg-white/50'
                }`}
              >
                <Globe className="w-4 h-4 text-[#e8c547] animate-pulse" />
                Google Maps 即時爬取
              </button>
            </div>

            {activeTab === 'preset' ? (
              <>


                {/* URL Input Slots */}
                <div className="space-y-4 mb-8 relative" ref={dropdownRef}>
                  {urls.map((url, index) => {
                    const isMatched = RESTAURANTS_DATA.some(r => r.name === url);
                    const matchedStore = RESTAURANTS_DATA.find(r => r.name === url);
                    const isEmpty = !url.trim();
                    
                    return (
                      <motion.div
                        key={index}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: index * 0.08 }}
                        className={`rounded-2xl p-4 border-2 transition-all duration-200 ${
                          isMatched
                            ? 'bg-[#6b8e7f]/10 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52]'
                            : isEmpty
                            ? 'bg-[#f5f1e8]/30 border-dashed border-[#d4c5b0] hover:bg-white hover:border-[#4a5d52] hover:shadow-[2px_2px_0px_0px_#4a5d52]'
                            : 'bg-white border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52]'
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <div className={`font-black px-2.5 py-0.5 rounded-md text-[10px] border ${
                            isMatched
                              ? 'bg-[#6b8e7f] text-white border-[#4a5d52]'
                              : isEmpty
                              ? 'bg-white text-[#6b8e7f] border-[#d4c5b0] border-dashed'
                              : 'bg-[#e8c547]/20 text-[#8b7534] border-[#e8c547]/40'
                          }`}>
                            對比店家 {index + 1}
                          </div>
                          {isMatched && matchedStore && (
                            <span className="text-[10px] font-bold text-[#4a5d52] flex items-center gap-1.5">
                              <Sparkles className="w-3.5 h-3.5 text-[#e8c547] animate-pulse" />
                              已載入：<span className="text-[#6b8e7f]">【{matchedStore.categoryLabel}】</span>
                            </span>
                          )}
                          {isEmpty && (
                            <span className="text-[10px] text-[#6b8e7f] font-semibold flex items-center gap-1 select-none">
                              點擊下方推薦或輸入店名載入
                            </span>
                          )}
                          {url && (
                            <motion.button
                              onClick={() => handleClear(index)}
                              whileHover={{ scale: 1.1 }}
                              whileTap={{ scale: 0.9 }}
                              className="ml-auto bg-[#d4a5a5] text-white p-1 rounded-full border border-[#4a5d52] cursor-pointer shadow-xs"
                            >
                              <X className="w-3.5 h-3.5" />
                            </motion.button>
                          )}
                        </div>
                        <div className="relative">
                          {isMatched ? (
                            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b8e7f]" />
                          ) : (
                            <LinkIcon className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#d4c5b0]" />
                          )}
                          
                          <input
                            type="text"
                            value={url}
                            onChange={(e) => handleUrlChange(index, e.target.value)}
                            onFocus={() => {
                              setActiveSlot(index);
                              setSearchQuery(url);
                            }}
                            placeholder="請在此輸入並搜尋店家名稱，或點擊下方推薦店卡片..."
                            className="w-full pl-10 pr-4 py-2.5 bg-white rounded-xl border border-[#d4c5b0] focus:border-[#6b8e7f] focus:ring-1 focus:ring-[#6b8e7f] outline-none text-xs md:text-sm text-[#4a5d52] font-semibold placeholder-[#a0b3a0] transition-shadow shadow-xs"
                          />

                          {/* Dropdown Suggestions */}
                          {activeSlot === index && filteredSuggestions.length > 0 && (
                            <div className="absolute left-0 right-0 top-full mt-2 bg-white rounded-xl shadow-lg border border-[#d4c5b0] z-50 max-h-56 overflow-y-auto">
                              {filteredSuggestions.map((restaurant) => (
                                <button
                                  key={restaurant.id}
                                  onClick={() => handleSelectRestaurant(index, restaurant)}
                                  className="w-full text-left px-4 py-2.5 hover:bg-[#6b8e7f]/10 flex items-center justify-between border-b border-[#f5f1e8] last:border-0 transition-colors text-xs"
                                >
                                  <div>
                                    <span className="font-extrabold text-[#4a5d52]">{restaurant.name}</span>
                                    <span className="ml-2 text-[10px] bg-[#e8dcc8] text-[#4a5d52] px-1.5 py-0.5 rounded">
                                      {restaurant.categoryLabel}
                                    </span>
                                  </div>
                                  <span className="text-[10px] text-[#6b8e7f] font-extrabold">
                                    {restaurant.isWashed ? '包含刷評' : '真實綠色'}
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </motion.div>
                    );
                  })}
                </div>

                {/* Main Action Button */}
                <motion.button
                  onClick={handleAnalyze}
                  disabled={isAnalyzing || matchedCount === 0}
                  whileHover={{ y: matchedCount > 0 && !isAnalyzing ? -4 : 0 }}
                  whileTap={{ y: matchedCount > 0 && !isAnalyzing ? 0 : 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
                  className="w-full bg-[#6b8e7f] hover:bg-[#5b7d6e] text-white font-black text-sm md:text-base py-4 rounded-full shadow-[4px_4px_0px_0px_#4a5d52] hover:shadow-[6px_6px_0px_0px_#4a5d52] disabled:shadow-none disabled:bg-[#c9bfae] disabled:cursor-not-allowed border-3 border-[#4a5d52] disabled:border-[#a0b3a0] transition-all cursor-pointer font-display tracking-wider active:translate-y-1 active:shadow-none"
                >
                  <AnimatePresence mode="wait">
                    {isAnalyzing ? (
                      <motion.div
                        key="analyzing"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex items-center justify-center gap-2"
                      >
                        <Loader2 className="w-5 h-5 animate-spin" />
                        雙階段過濾引擎計算中（正則篩選 + AI 語意複核）...
                      </motion.div>
                    ) : (
                      <motion.div
                        key="analyze"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex items-center justify-center gap-2 font-display text-base tracking-wide"
                      >
                        開始評價「濾水分析」（對比 {matchedCount} 間）
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.button>
              </>
            ) : (
              <div className="space-y-4">


                {scrapeError && (
                  <div className="p-3.5 bg-[#fde8e8] border-2 border-[#e53e3e] text-[#9b2c2c] rounded-2xl flex items-start gap-2.5">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-[#e53e3e]" />
                    <p className="flex-1 text-xs font-semibold leading-relaxed">{scrapeError}</p>
                    <button
                      onClick={() => setScrapeError('')}
                      className="text-[#9b2c2c] hover:opacity-80 font-black cursor-pointer"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}

                <div className="flex justify-between items-end mb-4">
                  <h3 className="text-[#4a5d52] font-black font-display text-sm">輸入即時爬取網址</h3>
                  <motion.button
                    onClick={handlePasteFromClipboard}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    className="flex items-center gap-1.5 text-xs font-black bg-white text-[#4a5d52] border-2 border-[#4a5d52] rounded-xl px-3 py-1.5 cursor-pointer shadow-[2px_2px_0px_0px_#4a5d52] active:translate-y-[2px] active:translate-x-[2px] active:shadow-none transition-all"
                  >
                    <ClipboardPaste className="w-3.5 h-3.5 text-[#6b8e7f]" />
                    從剪貼簿貼上
                  </motion.button>
                </div>

                <div className="space-y-4 mb-4">
                  {scrapeUrls.map((url, index) => {
                    const isEmpty = !url.trim();
                    return (
                      <motion.div
                        key={index}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: index * 0.08 }}
                        className={`rounded-2xl p-4 border-2 transition-all duration-200 ${
                          isEmpty
                            ? 'bg-[#f5f1e8]/30 border-dashed border-[#d4c5b0] hover:bg-white hover:border-[#4a5d52] hover:shadow-[2px_2px_0px_0px_#4a5d52]'
                            : 'bg-white border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52]'
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <div className={`font-black px-2.5 py-0.5 rounded-md text-[10px] border ${
                            isEmpty
                              ? 'bg-white text-[#6b8e7f] border-[#d4c5b0] border-dashed'
                              : 'bg-[#6b8e7f] text-white border-[#4a5d52]'
                          }`}>
                            即時爬取店家 {index + 1}
                          </div>
                          {url && (
                            <motion.button
                              onClick={() => handleScrapeUrlClear(index)}
                              whileHover={{ scale: 1.1 }}
                              whileTap={{ scale: 0.9 }}
                              className="ml-auto bg-[#d4a5a5] text-white p-1 rounded-full border border-[#4a5d52] cursor-pointer shadow-xs"
                            >
                              <X className="w-3.5 h-3.5" />
                            </motion.button>
                          )}
                        </div>
                        <div className="relative">
                          <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b8e7f]" />
                          <input
                            type="text"
                            value={url}
                            onChange={(e) => handleScrapeUrlChange(index, e.target.value)}
                            placeholder="請輸入 Google Maps 網址，或直接輸入店家名稱（例如：蘇草salvia）..."
                            className="w-full pl-10 pr-4 py-2.5 bg-white rounded-xl border border-[#d4c5b0] focus:border-[#6b8e7f] focus:ring-1 focus:ring-[#6b8e7f] outline-none text-xs md:text-sm text-[#4a5d52] font-semibold placeholder-[#a0b3a0] transition-shadow shadow-xs"
                          />
                        </div>
                      </motion.div>
                    );
                  })}
                </div>

                <div className="rounded-2xl p-5 bg-[#f5f1e8]/40 border border-[#e8dcc8]">
                  <div className="flex justify-between items-center mb-1.5">
                    <label className="text-xs font-black text-[#4a5d52] flex items-center gap-1.5">
                      <Sliders className="w-3.5 h-3.5" />
                      限制抓取評論筆數 (每間商家)
                    </label>
                    <span className="text-[10px] font-extrabold text-[#6b8e7f] bg-white px-2 py-0.5 rounded border border-[#d4c5b0]">
                      {maxReviews} 筆
                    </span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="200"
                    step="10"
                    value={maxReviews}
                    onChange={(e) => setMaxReviews(parseInt(e.target.value))}
                    className="w-full accent-[#6b8e7f] h-1.5 bg-[#e8dcc8] rounded-lg appearance-none cursor-pointer"
                  />
                </div>

                <motion.button
                  onClick={handleScrapeAndAnalyze}
                  disabled={isAnalyzing || filledScrapeCount === 0}
                  whileHover={{ scale: filledScrapeCount > 0 && !isAnalyzing ? 1.02 : 1 }}
                  whileTap={{ scale: filledScrapeCount > 0 && !isAnalyzing ? 0.98 : 1 }}
                  className="w-full bg-gradient-to-r from-[#6b8e7f] to-[#4a5d52] hover:opacity-95 text-white font-extrabold text-sm md:text-base py-3.5 rounded-full shadow-md disabled:from-[#c9bfae] disabled:to-[#c9bfae] disabled:cursor-not-allowed border-2 border-[#4a5d52] disabled:border-[#a0b3a0] transition-all cursor-pointer flex items-center justify-center gap-2"
                >
                  {isAnalyzing ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      {scrapeLoadingStep || '啟動自動爬蟲中...'}
                    </>
                  ) : (
                    <>
                      <Globe className="w-4 h-4 text-[#e8c547] animate-pulse" />
                      一鍵抓取評論並開啟 AI 審計 {filledScrapeCount > 0 ? `（共 ${filledScrapeCount} 間）` : ''}
                    </>
                  )}
                </motion.button>
              </div>
            )}
          </div>
        </div>



        {/* Preset Store Recommendations Grid */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="bg-white/90 backdrop-blur-xs rounded-[32px] p-6 border border-[#d4c5b0] shadow-xs"
        >
          <h2 className="text-sm md:text-base font-extrabold text-[#4a5d52] mb-5 flex items-center gap-1.5 font-display">
            快速點選測試數據集（推薦對照體驗）
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Ramen Panel */}
            <div className="space-y-3.5">
              <h3 className="font-extrabold text-xs md:text-sm text-[#4a5d52] flex items-center gap-1.5 border-b pb-1.5 border-[#d4c5b0]/40 font-display">
                日式拉麵對照
              </h3>
              <div className="space-y-2">
                {ramenPresets.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => handleAddPreset(r)}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-[11px] border font-semibold flex items-center justify-between transition-all hover:translate-x-1 cursor-pointer ${
                      r.isWashed
                        ? 'bg-[#d4a5a5]/10 hover:bg-[#d4a5a5]/20 border-[#d4a5a5]/30 text-[#8c4848]'
                        : 'bg-[#6b8e7f]/10 hover:bg-[#6b8e7f]/20 border-[#6b8e7f]/30 text-[#304a3e]'
                    }`}
                  >
                    <div>
                      <span className="font-extrabold block text-xs">{r.name}</span>
                      <span className="text-[9px] opacity-75 font-medium">
                        {r.isWashed ? '包含促銷好評送禮' : '自然有機真實評論'}
                      </span>
                    </div>
                    <Plus className="w-3.5 h-3.5 shrink-0 ml-1" />
                  </button>
                ))}
              </div>
            </div>

            {/* Bento Panel */}
            <div className="space-y-3.5">
              <h3 className="font-extrabold text-xs md:text-sm text-[#4a5d52] flex items-center gap-1.5 border-b pb-1.5 border-[#d4c5b0]/40 font-display">
                健康便當對照
              </h3>
              <div className="space-y-2">
                {bentoPresets.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => handleAddPreset(r)}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-[11px] border font-semibold flex items-center justify-between transition-all hover:translate-x-1 cursor-pointer ${
                      r.isWashed
                        ? 'bg-[#d4a5a5]/10 hover:bg-[#d4a5a5]/20 border-[#d4a5a5]/30 text-[#8c4848]'
                        : 'bg-[#6b8e7f]/10 hover:bg-[#6b8e7f]/20 border-[#6b8e7f]/30 text-[#304a3e]'
                    }`}
                  >
                    <div>
                      <span className="font-extrabold block text-xs">{r.name}</span>
                      <span className="text-[9px] opacity-75 font-medium">
                        {r.isWashed ? '包含打卡送茶飲' : '綠色低卡便當口碑'}
                      </span>
                    </div>
                    <Plus className="w-3.5 h-3.5 shrink-0 ml-1" />
                  </button>
                ))}
              </div>
            </div>

            {/* Drinks Panel */}
            <div className="space-y-3.5">
              <h3 className="font-extrabold text-xs md:text-sm text-[#4a5d52] flex items-center gap-1.5 border-b pb-1.5 border-[#d4c5b0]/40 font-display">
                手搖茶飲對照
              </h3>
              <div className="space-y-2">
                {drinkPresets.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => handleAddPreset(r)}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-[11px] border font-semibold flex items-center justify-between transition-all hover:translate-x-1 cursor-pointer ${
                      r.isWashed
                        ? 'bg-[#d4a5a5]/10 hover:bg-[#d4a5a5]/20 border-[#d4a5a5]/30 text-[#8c4848]'
                        : 'bg-[#6b8e7f]/10 hover:bg-[#6b8e7f]/20 border-[#6b8e7f]/30 text-[#304a3e]'
                    }`}
                  >
                    <div>
                      <span className="font-extrabold block text-xs">{r.name}</span>
                      <span className="text-[9px] opacity-75 font-medium">
                        {r.isWashed ? '網紅洗好評買一送一' : '巷弄古早手搖老店'}
                      </span>
                    </div>
                    <Plus className="w-3.5 h-3.5 shrink-0 ml-1" />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </motion.div>

        {/* AI Config Card */}
        {!isPWA && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="mt-8 bg-white/90 backdrop-blur-xs rounded-[32px] p-6 border border-[#d4c5b0] shadow-xs flex flex-col md:flex-row items-center gap-6"
          >
            <div className="flex-1 space-y-3">
              <h3 className="text-[#4a5d52] font-black flex items-center gap-2 font-display">
                <ShieldCheck className="w-5 h-5 text-[#6b8e7f]" />
                雙階段審查：正則規則引擎 + AI 語意防護網
              </h3>
              <p className="text-xs text-[#6b8e7f] leading-relaxed font-bold">
                這套工具並非單純呼叫語言模型。第一階段先由 Python Regex 引擎掃描評論區「五星贈送」、「打卡送」等字詞，進行硬性剃除；第二階段才會將剩餘模糊評論（以及密集期）整包送到 Gemini Flash 1.5 進行上下文語意溯源，判斷是否為集團化網軍操作，實現極高準確度的洗評過濾。
              </p>
            </div>
            <div className="shrink-0">
              <Sliders className="w-12 h-12 text-[#d4c5b0]/50" />
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}
