import { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate } from 'react-router';
import { ArrowLeft, Loader2, X, Globe, Sliders, ShieldCheck, Shield, AlertTriangle, ClipboardPaste, Key, ExternalLink, Eye, EyeOff, Info } from 'lucide-react';
import { useIsPWA } from '../hooks/useIsPWA';
import { TutorialModal, TUTORIAL_STORAGE_KEY } from '../components/TutorialModal';
import { DisclaimerModal, DISCLAIMER_STORAGE_KEY } from '../components/DisclaimerModal';

export function Analyzer() {
  const navigate = useNavigate();
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const isPWA = useIsPWA();

  // First visit: auto-show tutorial, then disclaimer after tutorial closes
  const [showTutorial, setShowTutorial] = useState(false);
  const [showDisclaimer, setShowDisclaimer] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem(TUTORIAL_STORAGE_KEY)) {
      setShowTutorial(true);
    }
    fetch('/api/log-visit', { method: 'POST' }).catch(() => {});
  }, []);

  const [scrapeUrls, setScrapeUrls] = useState<string[]>(['', '', '']);
  const [scrapeLoadingStep, setScrapeLoadingStep] = useState('');
  const [scrapeError, setScrapeError] = useState('');
  const [categoryReport, setCategoryReport] = useState<{
    placeId: string; storeName: string; categoryName: string;
  } | null>(null);
  const [reportSent, setReportSent] = useState(false);

  // Credentials prompt — shown only when a cache miss requires user keys
  const [showCredentials, setShowCredentials] = useState(false);
  const [apifyToken, setApifyToken] = useState(() => sessionStorage.getItem('truerating_apify_token') || '');
  const [aiKey, setAiKey] = useState(() =>
    sessionStorage.getItem('truerating_gemini_api_key') ||
    sessionStorage.getItem('truerating_deepseek_api_key') || ''
  );
  const [showApifyToken, setShowApifyToken] = useState(false);
  const [showAiKey, setShowAiKey] = useState(false);
  const [showKeyGuide, setShowKeyGuide] = useState(false);

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
    const key = aiKey.trim();
    if (key) {
      if (key.startsWith('AIzaSy')) {
        sessionStorage.setItem('truerating_llm_provider', 'gemini');
        sessionStorage.setItem('truerating_gemini_api_key', key);
        sessionStorage.removeItem('truerating_deepseek_api_key');
      } else if (key.startsWith('sk-')) {
        sessionStorage.setItem('truerating_llm_provider', 'deepseek');
        sessionStorage.setItem('truerating_deepseek_api_key', key);
        sessionStorage.removeItem('truerating_gemini_api_key');
      } else {
        // Default to Gemini — server will validate
        sessionStorage.setItem('truerating_llm_provider', 'gemini');
        sessionStorage.setItem('truerating_gemini_api_key', key);
      }
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
    if (savedApify) headers['X-Apify-Token'] = savedApify;
    const savedProvider = sessionStorage.getItem('truerating_llm_provider') || 'gemini';
    if (savedProvider === 'deepseek') {
      const k = sessionStorage.getItem('truerating_deepseek_api_key');
      if (k) headers['X-DeepSeek-API-Key'] = k;
    } else {
      const k = sessionStorage.getItem('truerating_gemini_api_key');
      if (k) headers['X-Gemini-API-Key'] = k;
    }

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
            body: JSON.stringify({ url: currentUrl, maxReviews: 500 })
          });

          const data = await response.json().catch(() => null);

          if (!response.ok) {
            // If server says credentials required, surface the prompt
            if (data?.code === 'CREDENTIALS_REQUIRED') {
              throw { credentialsRequired: true, message: data.error };
            }
            if (data?.code === 'NOT_RESTAURANT') {
              throw {
                notRestaurant: true,
                message: data.error,
                placeId: data.placeId,
                storeName: data.storeName,
                categoryName: data.categoryName,
              };
            }
            throw new Error(data?.error || '伺服器爬取失敗，請確認網址正確或稍後再試。');
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

          const meta = data.metadata || {};
          const displayName = meta.title || storeName;
          const categoryTag = meta.categoryName ? ` (${meta.categoryName})` : '';

          return {
            id: data.place_id || `custom_scraped_shop_${i}`,
            name: displayName + categoryTag,
            reviews: mappedReviews,
            metadata: meta,
            dataAsOf: data.dataAsOf,
            scrapeSource: data.source || '',
          };
        } catch (e: any) {
          if (e.credentialsRequired || e.notRestaurant) throw e;
          throw new Error(`[${storeName}] 爬取失敗: ${e.message || '請確認網址正確或稍後再試'}`);
        }
      });

      const customShops = await Promise.all(promises);

      navigate('/results', {
        state: { storeIds: [], customShops }
      });
    } catch (e: any) {
      console.error(e);
      if (e.notRestaurant) {
        setScrapeError(e.message);
        setCategoryReport({
          placeId: e.placeId || '',
          storeName: e.storeName || '',
          categoryName: e.categoryName || '',
        });
        setReportSent(false);
      } else if (e.credentialsRequired) {
        setShowCredentials(true);
        setScrapeError('此店家尚未收錄於資料庫，需要您提供 API 金鑰才能即時爬取。請在下方填入後重試。');
      } else {
        setScrapeError(e.message || '爬取過程中發生未知錯誤，請稍後再試。');
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

      {showTutorial && (
        <TutorialModal onClose={() => {
          setShowTutorial(false);
          // Chain: show disclaimer after tutorial if not yet accepted
          if (!localStorage.getItem(DISCLAIMER_STORAGE_KEY)) {
            setShowDisclaimer(true);
          }
        }} />
      )}
      {showDisclaimer && <DisclaimerModal />}

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
              <div className="flex-1">
                <p className="text-sm leading-relaxed">{scrapeError}</p>
                {categoryReport && !reportSent && (
                  <button
                    onClick={async () => {
                      try {
                        await fetch('/api/report-category', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify(categoryReport),
                        });
                        setReportSent(true);
                      } catch {
                        // silent
                      }
                    }}
                    className="mt-2 text-xs px-3 py-1.5 rounded-lg bg-[var(--semantic-danger)]/20 hover:bg-[var(--semantic-danger)]/30 transition-colors cursor-pointer"
                  >
                    這其實是餐飲店？點此回報
                  </button>
                )}
                {reportSent && (
                  <p className="mt-2 text-xs text-ink-subtle">已回報，感謝您的協助！</p>
                )}
              </div>
              <button
                onClick={() => { setScrapeError(''); setShowCredentials(false); setCategoryReport(null); }}
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
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Key className="w-4 h-4 text-primary" />
                      <h3 className="text-sm font-medium text-ink">自訂爬取設定</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowKeyGuide(v => !v)}
                      className="w-6 h-6 rounded-full border border-hairline flex items-center justify-center text-ink-tertiary hover:text-ink hover:border-hairline-strong transition-colors cursor-pointer"
                      title="如何取得金鑰？"
                    >
                      <Info className="w-3 h-3" />
                    </button>
                  </div>

                  <AnimatePresence>
                    {showKeyGuide && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="bg-surface-3 rounded-lg p-4 text-xs text-ink-subtle leading-relaxed space-y-2 mb-2">
                          <p className="font-medium text-ink text-sm">如何查詢未收錄的店家？</p>
                          <p>資料庫目前收錄臺大周邊 1,500+ 家餐廳。查詢其他地區的店家需要免費的 Apify Token 即時爬取評論。</p>
                          <ol className="list-decimal list-inside space-y-1">
                            <li>前往 <a href="https://apify.com/sign-up" target="_blank" rel="noreferrer" className="text-primary hover:text-primary-hover underline">apify.com</a> 註冊免費帳號（每月 $5 美元免費額度）</li>
                            <li>到 <a href="https://console.apify.com/account/integrations" target="_blank" rel="noreferrer" className="text-primary hover:text-primary-hover underline">帳號設定 → Integrations</a> 複製 API Token</li>
                            <li>貼到下方「Apify Token」欄位，點擊重試即可</li>
                          </ol>
                          <p>AI 審計需要您自己的 Gemini 或 DeepSeek API Key（<a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-primary hover:text-primary-hover underline">Gemini 免費申請</a>），系統會自動辨識金鑰類型。</p>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <p className="text-xs text-ink-subtle leading-relaxed">
                    此店家尚未收錄，需提供 Apify Token 即時爬取。
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

                  {/* AI API Key */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-medium text-ink-subtle">
                        AI API Key <span className="text-[var(--semantic-danger)]">*</span>
                      </label>
                      <a
                        href="https://aistudio.google.com/app/apikey"
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] text-primary hover:text-primary-hover flex items-center gap-1"
                      >
                        免費申請 Gemini Key <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                    <div className="relative">
                      <input
                        type={showAiKey ? 'text' : 'password'}
                        value={aiKey}
                        onChange={(e) => setAiKey(e.target.value)}
                        placeholder="AIzaSy... 或 sk-...（自動辨識 Gemini / DeepSeek）"
                        className="w-full bg-surface-3 border border-hairline rounded-lg px-3 py-2.5 text-sm text-ink placeholder-ink-tertiary focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none pr-10 transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => setShowAiKey(!showAiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle cursor-pointer"
                      >
                        {showAiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {/* Time estimate warning */}
                  <div className="bg-[var(--semantic-warning,#f59e0b)]/10 border border-[var(--semantic-warning,#f59e0b)]/20 rounded-lg p-3 text-xs text-ink-subtle leading-relaxed flex items-start gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[var(--semantic-warning,#f59e0b)]" />
                    <span>即時爬取每間店家約需 <strong className="text-ink">1～3 分鐘</strong>，視評論數量而定。爬取期間請勿關閉頁面。Apify 每次爬取約 $0.05 美元，AI 審計約 $0.01 美元。</span>
                  </div>

                  <motion.button
                    onClick={handleRetryWithCredentials}
                    disabled={!apifyToken.trim() || !aiKey.trim()}
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
                第一階段由 Python 規則引擎掃描評論結構特徵（促銷關鍵字、模板化用語等）進行初步分類；第二階段將模糊評論送至 AI 進行語意分析，識別不自然的評論模式。資料庫已收錄的店家可直接查詢；未收錄的店家需要您提供 Apify Token 即時爬取。
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
