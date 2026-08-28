import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate } from 'react-router';
import { ArrowLeft, Loader2, X, Globe, Sliders, ShieldCheck, Shield, AlertTriangle, ClipboardPaste, Key, ExternalLink, Eye, EyeOff, Info } from 'lucide-react';
import { useIsPWA } from '../hooks/useIsPWA';
import { TutorialModal } from '../components/TutorialModal';

export function Analyzer() {
  const navigate = useNavigate();
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const isPWA = useIsPWA();
  const [showTutorial, setShowTutorial] = useState(false);

  const [scrapeUrls, setScrapeUrls] = useState<string[]>(['', '', '']);
  const [maxReviews, setMaxReviews] = useState(50);
  const [scrapeLoadingStep, setScrapeLoadingStep] = useState('');
  const [scrapeError, setScrapeError] = useState('');

  // Credentials prompt — shown only when a cache miss requires user keys
  const [showCredentials, setShowCredentials] = useState(false);
  const [apifyToken, setApifyToken] = useState(() => sessionStorage.getItem('truerating_apify_token') || '');
  const [geminiKey, setGeminiKey] = useState(() => sessionStorage.getItem('truerating_gemini_api_key') || '');
  const [showApifyToken, setShowApifyToken] = useState(false);
  const [showGeminiKey, setShowGeminiKey] = useState(false);

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
      } else {
        alert('剪貼簿中未偵測到有效的 Google Maps 連結。');
      }
    } catch (err) {
      console.warn('Clipboard read permission denied or not supported:', err);
      alert('無法讀取剪貼簿，請確認瀏覽器授權。');
    }
  }, [scrapeUrls]);

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

  const saveCredentials = () => {
    if (apifyToken.trim()) {
      sessionStorage.setItem('truerating_apify_token', apifyToken.trim());
    }
    if (geminiKey.trim()) {
      sessionStorage.setItem('truerating_gemini_api_key', geminiKey.trim());
    }
  };

  const handleScrapeAndAnalyze = async () => {
    const activeUrls = scrapeUrls.map(u => u.trim()).filter(Boolean);
    if (activeUrls.length === 0) return;

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
      '正在查詢資料庫快取...',
      '正在向 Apify 送出抓取請求...',
      '正在解析評論文字、發布時間與打卡照片...',
      '正在整理資料格式...'
    ];
    let stepIdx = 0;
    const interval = setInterval(() => {
      if (stepIdx < steps.length) {
        setScrapeLoadingStep(steps[stepIdx]);
        stepIdx++;
      }
    }, 3000);

    // Build headers with user credentials if available
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const savedApify = sessionStorage.getItem('truerating_apify_token');
    const savedGemini = sessionStorage.getItem('truerating_gemini_api_key');
    if (savedApify) headers['X-Apify-Token'] = savedApify;
    if (savedGemini) headers['X-Gemini-API-Key'] = savedGemini;

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
            headers,
            body: JSON.stringify({ url: currentUrl, maxReviews })
          });

          const data = await response.json().catch(() => null);

          if (!response.ok) {
            // If server says credentials required, surface the prompt
            if (data?.code === 'CREDENTIALS_REQUIRED') {
              throw { credentialsRequired: true, message: data.error };
            }
            throw new Error(data?.error || '伺服器爬取失敗，請確認本地爬蟲伺服器已開啟，且網址正確。');
          }

          if (!data?.reviews || data.reviews.length === 0) {
            throw new Error('無法抓取到任何評論，可能是網址無效或 Google 正在阻擋爬蟲請求。');
          }

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
          if (e.credentialsRequired) throw e;
          throw new Error(`[${storeName}] 爬取失敗: ${e.message || '請確認本地後端服務已開啟'}`);
        }
      });

      const customShops = await Promise.all(promises);

      navigate('/results', {
        state: { storeIds: [], customShops }
      });
    } catch (e: any) {
      console.error(e);
      if (e.credentialsRequired) {
        setShowCredentials(true);
        setScrapeError('此店家尚未收錄於資料庫，需要您提供 API 金鑰才能即時爬取。請在下方填入後重試。');
      } else {
        setScrapeError(e.message || '爬取過程中發生未知錯誤，請確認本地爬蟲伺服器已開啟。');
      }
    } finally {
      clearInterval(interval);
      setIsAnalyzing(false);
      setScrapeLoadingStep('');
    }
  };

  const handleRetryWithCredentials = () => {
    saveCredentials();
    setScrapeError('');
    handleScrapeAndAnalyze();
  };

  const filledScrapeCount = scrapeUrls.filter(url => url.trim() !== '').length;

  return (
    <div className="min-h-screen bg-background font-sans selection:bg-primary/20 pb-12">
      {/* Navigation Header */}
      <header className="sticky top-0 z-50 bg-background border-b border-hairline px-4 md:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
          <div className="bg-ink text-background w-8 h-8 rounded flex items-center justify-center">
            <Shield className="w-4.5 h-4.5" />
          </div>
          <span className="font-sans font-semibold text-base text-ink tracking-[-0.4px]">
            疑騙真星
            <span className="text-ink-subtle font-normal text-sm ml-1.5">TrueRating</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTutorial(true)}
            className="w-7 h-7 rounded border border-hairline flex items-center justify-center text-ink-subtle hover:text-ink hover:border-hairline-strong transition-colors cursor-pointer"
            title="使用教學"
          >
            <Info className="w-3.5 h-3.5" />
          </button>
          {!isPWA && (
            <button
              onClick={() => navigate('/')}
              className="flex items-center gap-1.5 bg-surface-2 px-4 py-1.5 rounded border border-hairline text-xs font-medium text-ink-subtle cursor-pointer hover:text-ink transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              返回首頁
            </button>
          )}
        </div>
      </header>

      {showTutorial && <TutorialModal onClose={() => setShowTutorial(false)} />}

      <div className="container mx-auto px-4 py-8 max-w-3xl">

        {/* Main Analysis Card */}
        <div className="bg-surface-1 rounded-xl p-6 md:p-8 border border-hairline mb-6">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center mb-8"
          >
            <h1 className="text-xl md:text-2xl font-semibold text-ink tracking-[-0.6px]">
              評論結構對比分析儀
            </h1>
            <p className="text-sm text-ink-subtle mt-2">
              輸入 Google Maps 網址或店家名稱，即時抓取評論並進行 AI 結構審計
            </p>
          </motion.div>

          {scrapeError && (
            <div className="p-3.5 bg-[var(--semantic-danger)]/10 border border-[var(--semantic-danger)]/20 text-[var(--semantic-danger)] rounded-xl flex items-start gap-2.5 mb-4">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <p className="flex-1 text-sm leading-relaxed">{scrapeError}</p>
              <button
                onClick={() => { setScrapeError(''); setShowCredentials(false); }}
                className="text-[var(--semantic-danger)] hover:opacity-80 cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Credentials Panel — shown only on cache miss */}
          <AnimatePresence>
            {showCredentials && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden mb-6"
              >
                <div className="bg-surface-2 rounded-xl p-5 border border-hairline space-y-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Key className="w-4 h-4 text-primary" />
                    <h3 className="text-sm font-medium text-ink">請提供您的 API 金鑰</h3>
                  </div>
                  <p className="text-xs text-ink-subtle leading-relaxed">
                    此店家不在資料庫快取中，需透過 Apify 即時爬取評論。審計階段使用 Gemini AI（選填，不填則使用伺服器預設金鑰）。
                  </p>

                  {/* Apify Token */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-medium text-ink-subtle">
                        Apify Token <span className="text-[var(--semantic-danger)]">*</span>
                      </label>
                      <a
                        href="https://console.apify.com/account/integrations"
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] text-primary hover:text-primary-hover flex items-center gap-1"
                      >
                        取得 Token <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                    <div className="relative">
                      <input
                        type={showApifyToken ? 'text' : 'password'}
                        value={apifyToken}
                        onChange={(e) => setApifyToken(e.target.value)}
                        placeholder="apify_api_..."
                        className="w-full bg-surface-3 border border-hairline rounded-lg px-3 py-2.5 text-sm text-ink placeholder-ink-tertiary focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none pr-10 transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApifyToken(!showApifyToken)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle cursor-pointer"
                      >
                        {showApifyToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {/* Gemini Key */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-medium text-ink-subtle">
                        Gemini API Key（選填）
                      </label>
                      <a
                        href="https://aistudio.google.com/app/apikey"
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] text-primary hover:text-primary-hover flex items-center gap-1"
                      >
                        取得金鑰 <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                    <div className="relative">
                      <input
                        type={showGeminiKey ? 'text' : 'password'}
                        value={geminiKey}
                        onChange={(e) => setGeminiKey(e.target.value)}
                        placeholder="AIzaSy...（不填則使用免費 Flash Lite）"
                        className="w-full bg-surface-3 border border-hairline rounded-lg px-3 py-2.5 text-sm text-ink placeholder-ink-tertiary focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none pr-10 transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => setShowGeminiKey(!showGeminiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle cursor-pointer"
                      >
                        {showGeminiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  <motion.button
                    onClick={handleRetryWithCredentials}
                    disabled={!apifyToken.trim()}
                    whileTap={{ scale: 0.98 }}
                    className="w-full bg-primary hover:bg-primary-hover text-white font-medium text-sm py-2.5 rounded-lg disabled:bg-surface-3 disabled:text-ink-tertiary disabled:cursor-not-allowed transition-all cursor-pointer flex items-center justify-center gap-2"
                  >
                    <Key className="w-4 h-4" />
                    儲存金鑰並重試爬取
                  </motion.button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="flex justify-between items-end mb-4">
            <h3 className="text-ink font-medium text-sm">輸入店家網址或名稱</h3>
            <motion.button
              onClick={handlePasteFromClipboard}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="flex items-center gap-1.5 text-xs font-medium bg-surface-2 text-ink-subtle border border-hairline rounded-lg px-3 py-1.5 cursor-pointer hover:text-ink hover:border-hairline-strong transition-all"
            >
              <ClipboardPaste className="w-3.5 h-3.5" />
              從剪貼簿貼上
            </motion.button>
          </div>

          <div className="space-y-3 mb-6">
            {scrapeUrls.map((url, index) => {
              const isEmpty = !url.trim();
              return (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.08 }}
                  className={`rounded-xl p-4 border transition-all duration-200 ${
                    isEmpty
                      ? 'bg-surface-2 border-hairline border-dashed hover:border-hairline-strong'
                      : 'bg-surface-2 border-hairline-strong'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-md ${
                      isEmpty
                        ? 'bg-surface-3 text-ink-tertiary'
                        : 'bg-primary/15 text-primary'
                    }`}>
                      店家 {index + 1}
                    </span>
                    {url && (
                      <motion.button
                        onClick={() => handleScrapeUrlClear(index)}
                        whileHover={{ scale: 1.1 }}
                        whileTap={{ scale: 0.9 }}
                        className="ml-auto bg-[var(--semantic-danger)] text-white p-1 rounded-md cursor-pointer"
                      >
                        <X className="w-3 h-3" />
                      </motion.button>
                    )}
                  </div>
                  <div className="relative">
                    <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-tertiary" />
                    <input
                      type="text"
                      value={url}
                      onChange={(e) => handleScrapeUrlChange(index, e.target.value)}
                      placeholder="Google Maps 網址或店家名稱（例如：蘇草salvia）..."
                      className="w-full pl-10 pr-4 py-2.5 bg-surface-2 rounded-lg border border-hairline focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none text-sm text-ink placeholder-ink-tertiary transition-all"
                    />
                  </div>
                </motion.div>
              );
            })}
          </div>

          <div className="rounded-xl p-4 bg-surface-2 border border-hairline mb-6">
            <div className="flex justify-between items-center mb-2">
              <label className="text-sm font-medium text-ink flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-ink-subtle" />
                抓取評論筆數（每間商家）
              </label>
              <span className="text-xs font-medium text-primary bg-primary/10 px-2 py-0.5 rounded-md">
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
              className="w-full accent-primary h-1 bg-surface-3 rounded-lg appearance-none cursor-pointer"
            />
          </div>

          <motion.button
            onClick={handleScrapeAndAnalyze}
            disabled={isAnalyzing || filledScrapeCount === 0}
            whileHover={{ y: filledScrapeCount > 0 && !isAnalyzing ? -2 : 0 }}
            whileTap={{ scale: filledScrapeCount > 0 && !isAnalyzing ? 0.98 : 1 }}
            className="w-full bg-primary hover:bg-primary-hover text-white font-medium text-sm md:text-base py-3.5 rounded-lg disabled:bg-surface-3 disabled:text-ink-tertiary disabled:cursor-not-allowed transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            {isAnalyzing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {scrapeLoadingStep || '啟動自動爬蟲中...'}
              </>
            ) : (
              <>
                <Globe className="w-4 h-4" />
                一鍵抓取評論並開啟 AI 審計{filledScrapeCount > 0 ? `（共 ${filledScrapeCount} 間）` : ''}
              </>
            )}
          </motion.button>
        </div>

        {/* AI Engine Info */}
        {!isPWA && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-surface-1 rounded-xl p-6 border border-hairline flex flex-col md:flex-row items-center gap-6"
          >
            <div className="flex-1 space-y-2">
              <h3 className="text-ink font-medium flex items-center gap-2 tracking-[-0.4px]">
                <ShieldCheck className="w-5 h-5 text-primary" />
                雙階段審查：正則規則引擎 + AI 語意防護網
              </h3>
              <p className="text-sm text-ink-subtle leading-relaxed">
                第一階段由 Python 規則引擎掃描評論結構特徵（促銷關鍵字、模板化用語等）進行初步分類；第二階段將模糊評論送至 Gemini 進行語意分析，識別不自然的評論模式。資料庫已收錄的店家可直接查詢；未收錄的店家需要您提供 Apify Token 即時爬取。
              </p>
            </div>
            <div className="shrink-0">
              <Sliders className="w-10 h-10 text-ink-tertiary" />
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}
