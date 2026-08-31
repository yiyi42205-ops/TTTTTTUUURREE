import { useState, useEffect, useRef } from 'react';
import { motion } from 'motion/react';
import { useNavigate, useLocation } from 'react-router';
import {
  ArrowLeft, AlertTriangle, Shield, X, Database, MessageSquare, Send,
  Loader2, Sparkles, Trophy, AlertCircle, ThumbsUp, Info
} from 'lucide-react';
import { RESTAURANTS_DATA } from '../data/restaurantsData';
import { parseReviews, Review } from '../utils/csvParser';
import { aggregateAuditedReviews, mergeStage2Results, ShopStats, AuditResult, SimilaritySignal, HotTermSignal } from '../utils/auditEngine';
import { ResponsiveContainer, BarChart, CartesianGrid, XAxis, YAxis, Tooltip, Bar } from 'recharts';
import { useIsPWA } from '../hooks/useIsPWA';
import { historyStore } from '../utils/historyStore';

// Report components
import { StoreVerdict } from '../components/results/StoreVerdict';
import { RatingChart } from '../components/results/RatingChart';
import { ReviewInspector, ReviewInspectorHandle } from '../components/results/ReviewInspector';
import { LoadingState } from '../components/results/LoadingState';
import { Footer } from '../components/Footer';
import { getLLMSettings, hasLLMKey } from '../utils/llmProvider';
import { TutorialModal } from '../components/TutorialModal';
import { DisclaimerModal } from '../components/DisclaimerModal';

function cleanStoreName(name: string): string {
  if (!name) return '';
  const parts = name.split(',');
  if (parts.length <= 1) return name.trim();

  const addressKeywords = [
    'city', 'district', 'town', 'county', 'road', 'street', 'lane', 'alley', 'section', 'village',
    '市', '區', '鄉', '鎮', '縣', '路', '街', '巷', '弄', '段', '里'
  ];

  const nonAddressParts = parts.filter(part => {
    const lower = part.toLowerCase();
    return !addressKeywords.some(keyword => lower.includes(keyword));
  });

  if (nonAddressParts.length > 0) {
    return nonAddressParts[nonAddressParts.length - 1].trim();
  }

  return parts[parts.length - 1].trim();
}

export function Results() {
  const navigate = useNavigate();
  const location = useLocation();

  const isPWA = useIsPWA();
  const isHistoryCache = !!location.state?.cachedShopResults;

  const storeIds = (location.state?.storeIds as string[]) || ['ramen_washed_3', 'ramen_clean_2'];

  // Base state computed from CSV data and local heuristic engine
  const [shopResults, setShopResults] = useState<ShopStats[]>([]);

  // Review Inspector Search & Filter states for each shop index
  const [inspectSearch, setInspectSearch] = useState<{ [key: number]: string }>({});
  const [inspectFilter, setInspectFilter] = useState<{ [key: number]: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean' | 'unaudited' }>({});

  // Backend signals from /api/audit-rules, keyed by store ID
  const [shopSignals, setShopSignals] = useState<{ [storeId: string]: {
    similarity: SimilaritySignal[];
    hotTerm: HotTermSignal[];
    nearbyLongReviewCounts: number[];
    spikeMonths: string[];
  } }>({});

  const [isAiAuditing, setIsAiAuditing] = useState(false);
  const [aiAuditResults, setAiAuditResults] = useState<{ [storeId: string]: { [username: string]: AuditResult } }>({});
  const [apiError, setApiError] = useState('');

  // Accordion state for CoT reasoning paths
  const [expandedCoT, setExpandedCoT] = useState<{ [key: string]: boolean }>({});

  // Active store tab selected in the top switcher
  const [activeStoreTab, setActiveStoreTab] = useState<number>(0);

  // Two-Stage Pipeline Logs State
  interface PipelineLog {
    storeId: string;
    storeName: string;
    totalReviews: number;
    stage1Count: number;
    stage2Sent: number;
    stage2Flagged: number;
    stage2Passed: number;
  }
  const [pipelineLogs, setPipelineLogs] = useState<PipelineLog[]>([]);

  // AI QA States
  const [qaInput, setQaInput] = useState<{ [storeIdx: number]: string }>({});
  const [isQaLoading, setIsQaLoading] = useState<{ [storeIdx: number]: boolean }>({});
  const [qaResults, setQaResults] = useState<{ [storeIdx: number]: any }>({});
  const [qaErrors, setQaErrors] = useState<{ [storeIdx: number]: string }>({});

  // Store summary states
  const [storeSummaries, setStoreSummaries] = useState<{ [storeIdx: number]: { warnings: any[]; recommendations: any[] } }>({});
  const [isSummaryLoading, setIsSummaryLoading] = useState<{ [storeIdx: number]: boolean }>({});

  const [showTutorial, setShowTutorial] = useState(false);

  // ReviewInspector ref for source click navigation
  const inspectorRef = useRef<ReviewInspectorHandle>(null);

  const handleSourceClick = (reviewId: string) => {
    inspectorRef.current?.expandAndSearch(reviewId);
  };

  // 1. Initial Parse -> call backend /api/audit-rules for Stage 1 heuristics
  useEffect(() => {
    if (location.state?.cachedShopResults) {
      const computed = location.state.cachedShopResults as ShopStats[];
      setShopResults(computed);

      const initialSearch: { [key: number]: string } = {};
      const initialFilter: { [key: number]: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean' | 'unaudited' } = {};
      computed.forEach((_, idx) => {
        initialSearch[idx] = '';
        initialFilter[idx] = 'all';
      });
      setInspectSearch(initialSearch);
      setInspectFilter(initialFilter);
      return;
    }

    const runStage1 = async () => {
      const customShops = (location.state?.customShops as Array<{ id: string; name: string; reviews: Review[]; metadata?: { totalScore?: number; reviewsCount?: number }; dataAsOf?: string }>) || [];

      let shopsToProcess: { id: string; name: string; reviews: Review[]; metadata?: { totalScore?: number; reviewsCount?: number }; dataAsOf?: string }[];
      if (customShops.length > 0) {
        shopsToProcess = customShops;
      } else {
        const activeIds = storeIds.length > 0 ? storeIds : ['ramen_washed_3', 'ramen_clean_2'];
        shopsToProcess = activeIds.map(id => {
          const store = RESTAURANTS_DATA.find(r => r.id === id);
          if (!store) return null;
          const reviews = parseReviews(store.csvContent);
          return { id, name: store.name, reviews };
        }).filter(Boolean) as { id: string; name: string; reviews: Review[] }[];
      }

      const computed: ShopStats[] = [];
      const newSignals: typeof shopSignals = {};

      for (const shop of shopsToProcess) {
        try {
          const response = await fetch('/api/audit-rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reviews: shop.reviews }),
          });

          if (!response.ok) {
            throw new Error(`Stage 1 API returned ${response.status}`);
          }

          const data = await response.json();
          const auditedReviews = data.auditedReviews.map((r: any) => ({
            username: r.username,
            stars: typeof r.stars === 'number' ? r.stars : Number(r.stars),
            time: r.time,
            text: r.text,
            images: r.images || [],
            audit: r.audit as AuditResult,
          }));

          const stats = aggregateAuditedReviews(shop.name, auditedReviews);
          if (shop.metadata?.totalScore != null) {
            stats.originalRating = shop.metadata.totalScore;
          }
          if (shop.metadata?.reviewsCount != null) {
            stats.googleReviewsCount = shop.metadata.reviewsCount;
          }
          if ((shop as any).dataAsOf) {
            stats.dataAsOf = (shop as any).dataAsOf;
          }
          computed.push(stats);
          newSignals[shop.id] = data.signals;
        } catch (e: any) {
          console.error(`Stage 1 failed for ${shop.name}:`, e);
          setApiError(e.message || 'Stage 1 規則引擎 API 請求失敗');
        }
      }

      setShopResults(computed);
      setShopSignals(newSignals);

      const initialSearch: { [key: number]: string } = {};
      const initialFilter: { [key: number]: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean' | 'unaudited' } = {};
      computed.forEach((_, idx) => {
        initialSearch[idx] = '';
        initialFilter[idx] = 'all';
      });
      setInspectSearch(initialSearch);
      setInspectFilter(initialFilter);
    };

    runStage1();
  }, [location.state?.storeIds, location.state?.customShops, location.state?.cachedShopResults]);

  // 1.5. Auto-trigger AI Audit on mount once shopResults are computed
  useEffect(() => {
    if (location.state?.cachedShopResults) {
      return;
    }
    if (shopResults.length > 0 && !isAiAuditing && Object.keys(aiAuditResults).length === 0) {
      handleGeminiAudit(shopResults);
    }
  }, [shopResults, location.state?.cachedShopResults]);

  // 2. AI Live Audit execution (Two-Stage Hybrid Pipeline)
  const handleGeminiAudit = async (forcedShopResults?: ShopStats[]) => {
    const activeShopResults = forcedShopResults || shopResults;

    setApiError('');
    setIsAiAuditing(true);

    try {
      const newAiResults = { ...aiAuditResults };
      const logs: PipelineLog[] = [];

      for (let idx = 0; idx < activeShopResults.length; idx++) {
        const result = activeShopResults[idx];
        const customShopsRef = (location.state?.customShops as Array<{ id: string }>) || [];
        const id = storeIds[idx] || customShopsRef[idx]?.id || `custom_${idx}`;
        const reviews = result.auditedReviews;

        const signals = shopSignals[id];
        const spikeMonthsSet = new Set(signals?.spikeMonths || []);

        const stage1Count = reviews.filter(r => r.stars === 5 && r.audit.issueType !== null).length;

        const allAmbiguous = reviews.filter(r => r.stars === 5 && r.audit.issueType === null);

        const ambiguousReviews = allAmbiguous;

        const stage2Sent = ambiguousReviews.length;

        let stage2Flagged = 0;
        let stage2Passed = 0;
        const storeMap: { [username: string]: AuditResult } = {};

        if (stage2Sent > 0) {
          const now = new Date();
          // Simplified payload: LLM only sees id + text now; signals stay
          // server-side. We still send isSpikePeriod so the rule engine can
          // use it, and daysElapsed for batch ordering.
          const reviewsPayload = ambiguousReviews.map(r => {
            const month = r.time ? r.time.substring(0, 7) : '';
            const isSpikePeriod = spikeMonthsSet.has(month);
            let daysElapsed = 0;
            if (r.time) {
              const reviewDate = new Date(r.time);
              if (!isNaN(reviewDate.getTime())) {
                daysElapsed = Math.max(0, Math.floor((now.getTime() - reviewDate.getTime()) / (1000 * 60 * 60 * 24)));
              }
            }
            return {
              username: r.username,
              text: r.text,
              isSpikePeriod,
              daysElapsed,
            };
          });

          const customShopsForId = (location.state?.customShops as Array<{ id: string }>) || [];
          const placeId = storeIds[idx] || customShopsForId[idx]?.id || '';
          const llm = getLLMSettings();
          const response = await fetch('/api/audit', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...llm.headers,
            },
            body: JSON.stringify({
              storeName: result.storeName,
              placeId,
              reviews: reviewsPayload,
              ...llm.body,
            })
          });

          if (!response.ok) {
            const errData = await response.json().catch(() => null);
            throw new Error(errData?.error || (errData?.details || []).join('; ') || '後端 AI 語意審計請求失敗');
          }

          const responseJson = await response.json();
          const items: any[] = responseJson.results || [];

          items.forEach(item => {
            // Skip unscored items (LLM failed for this review)
            if (item.stage2 === 'unscored') return;

            if (item.isWashed) {
              stage2Flagged++;
            } else {
              stage2Passed++;
            }

            // Server now returns complete results with confidence computed
            storeMap[item.username] = {
              isWashed: item.isWashed,
              reason: item.reason,
              confidenceScore: item.confidenceScore,
              issueType: item.issueType === 'none' ? null : (item.issueType as any),
              reasoningPath: item.reasoningPath,
              incentiveIntensity: item.incentiveIntensity || 3,
              sentimentAuthenticity: item.sentimentAuthenticity || 3,
              descriptionGranularity: item.descriptionGranularity || 3,
              verdictBasis: item.verdictBasis,
            };
          });
        }

        logs.push({
          storeId: id,
          storeName: result.storeName,
          totalReviews: reviews.length,
          stage1Count,
          stage2Sent,
          stage2Flagged,
          stage2Passed
        });

        newAiResults[id] = storeMap;
      }

      setPipelineLogs(logs);
      setAiAuditResults(newAiResults);

      const updatedResults = activeShopResults.map((shop, idx) => {
        const customShopsMatch = (location.state?.customShops as Array<{ id: string }>) || [];
        const matchingId = storeIds[idx] || customShopsMatch[idx]?.id || `custom_${idx}`;

        if (!newAiResults[matchingId]) return shop;

        const aiStoreMap = newAiResults[matchingId];
        const updatedReviews = mergeStage2Results(shop.auditedReviews, aiStoreMap);

        return aggregateAuditedReviews(shop.storeName, updatedReviews);
      });

      setShopResults(updatedResults);
      updatedResults.forEach(shop => {
        historyStore.saveHistory(shop);
      });
    } catch (e: any) {
      console.error(e);
      setApiError(e.message || '連線 API 時發生未知錯誤');
    } finally {
      setIsAiAuditing(false);
    }
  };

  // Auto-fetch store summary after audit completes
  useEffect(() => {
    if (isAiAuditing || shopResults.length === 0) return;

    shopResults.forEach((shop, idx) => {
      if (storeSummaries[idx] || isSummaryLoading[idx]) return;

      const customShops = (location.state?.customShops as Array<{ id: string }>) || [];
      const placeId = storeIds[idx] || customShops[idx]?.id || '';
      if (!placeId) return;

      setIsSummaryLoading(prev => ({ ...prev, [idx]: true }));

      const validReviews = shop.auditedReviews
        .filter(r => !r.audit.isWashed && r.text && r.text.trim())
        .map(r => ({
          id: r.username,
          username: r.username,
          text: r.text,
          stars: r.stars,
          audit: r.audit,
        }));

      const summaryLlm = getLLMSettings();
      fetch('/api/store-summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...summaryLlm.headers },
        body: JSON.stringify({
          placeId,
          storeName: shop.storeName,
          reviews: validReviews,
          ...summaryLlm.body,
        }),
      })
        .then(res => res.json())
        .then(data => {
          if (data.warnings || data.recommendations) {
            setStoreSummaries(prev => ({ ...prev, [idx]: data }));
          }
        })
        .catch(e => console.error('Store summary failed:', e))
        .finally(() => setIsSummaryLoading(prev => ({ ...prev, [idx]: false })));
    });
  }, [isAiAuditing, shopResults]);

  const handleQaSubmit = async (storeIdx: number) => {
    const question = qaInput[storeIdx]?.trim();
    if (!question) return;

    if (!hasLLMKey()) {
      setQaErrors(prev => ({ ...prev, [storeIdx]: '請先在設定頁配置 AI 模型金鑰才能使用問答功能。' }));
      return;
    }

    const shop = shopResults[storeIdx];
    if (!shop) return;

    const validReviews = shop.auditedReviews
      .filter(r => !r.audit.isWashed && r.text && r.text.trim())
      .map(r => ({
        id: r.username,
        text: r.text,
        stars: r.stars,
        time: r.time
      }));

    setIsQaLoading(prev => ({ ...prev, [storeIdx]: true }));
    setQaErrors(prev => ({ ...prev, [storeIdx]: '' }));

    const llm = getLLMSettings();
    try {
      const response = await fetch('/api/summarize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...llm.headers,
        },
        body: JSON.stringify({
          placeId: storeIds[storeIdx] || ((location.state?.customShops as Array<{ id: string }>) || [])[storeIdx]?.id || shop.storeName,
          storeName: shop.storeName,
          reviews: validReviews,
          question: question,
          ...llm.body,
        })
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'QA 請求失敗');
      }

      setQaResults(prev => ({ ...prev, [storeIdx]: data }));
    } catch (e: any) {
      console.error('QA Error:', e);
      setQaErrors(prev => ({ ...prev, [storeIdx]: e.message || '連線錯誤' }));
    } finally {
      setIsQaLoading(prev => ({ ...prev, [storeIdx]: false }));
    }
  };

  const isComplete = shopResults.length > 0 && !isAiAuditing;
  const showLoader = isAiAuditing;

  let bestStoreIndex = 0;
  if (shopResults.length > 0) {
    let maxRating = -1;
    shopResults.forEach((shop, idx) => {
      if (shop.filteredRating > maxRating) {
        maxRating = shop.filteredRating;
        bestStoreIndex = idx;
      }
    });
  }

  const toggleCoT = (storeIndex: number, reviewIndex: number) => {
    const key = `${storeIndex}-${reviewIndex}`;
    setExpandedCoT(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  // ---- Header (shared between loading and complete states) ----
  const renderHeader = () => (
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
        <button
          onClick={() => navigate('/analyzer')}
          className="flex items-center gap-1.5 bg-surface-1 hover:bg-surface-2 px-4 py-1.5 rounded border border-hairline text-xs font-medium text-ink-muted cursor-pointer transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          返回修改
        </button>
      </div>
    </header>
  );

  // ---- Loading state ----
  if (!isComplete) {
    return (
      <div className="min-h-screen bg-background font-sans">
        <DisclaimerModal />
        {showTutorial && <TutorialModal onClose={() => setShowTutorial(false)} />}
        {renderHeader()}
        <LoadingState
          shopResults={shopResults}
          showLoader={showLoader}
          cleanStoreName={cleanStoreName}
        />
      </div>
    );
  }

  // ---- Complete state ----
  const activeResult = shopResults[activeStoreTab];

  return (
    <div className="min-h-screen bg-background font-sans pb-16">
      <DisclaimerModal />
      {showTutorial && <TutorialModal onClose={() => setShowTutorial(false)} />}
      {renderHeader()}

      <div className="container mx-auto px-4 py-6 max-w-3xl">
        {/* Page title */}
        <div className="mb-8">
          <div className="flex items-center gap-2">
            <h1 className="text-xl md:text-2xl font-semibold text-ink tracking-[-0.6px]">
              審計結果
            </h1>
            {isHistoryCache && (
              <span className="text-[11px] bg-surface-2 text-ink-subtle border border-hairline px-2 py-0.5 rounded font-medium flex items-center gap-1">
                <Database className="w-3 h-3" />
                歷史快取
              </span>
            )}
          </div>
        </div>

        {/* API error banner */}
        {apiError && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-6 p-4 bg-[var(--semantic-danger)]/10 border border-[var(--semantic-danger)]/20 text-[var(--semantic-danger)] rounded-xl flex items-start gap-3"
          >
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <div className="flex-1 space-y-0.5">
              <p className="text-sm font-medium">第二階段 AI 語意審計失敗</p>
              <p className="text-xs opacity-80">{apiError}</p>
            </div>
            <button
              onClick={() => setApiError('')}
              className="text-[var(--semantic-danger)] hover:opacity-80 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}

        {/* Store switcher tabs (if multiple stores) */}
        {shopResults.length > 1 && (
          <div className="flex gap-2 mb-6 overflow-x-auto pb-1">
            {shopResults.map((shop, idx) => {
              const isBest = idx === bestStoreIndex;
              return (
                <button
                  key={idx}
                  onClick={() => setActiveStoreTab(idx)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium shrink-0 border transition-colors cursor-pointer flex items-center gap-1.5 ${
                    activeStoreTab === idx
                      ? 'bg-primary text-white border-primary'
                      : 'bg-surface-1 text-ink-muted border-hairline hover:bg-surface-2 hover:text-ink'
                  }`}
                >
                  {isBest && shopResults.length > 1 && <Trophy className="w-3.5 h-3.5 text-[var(--semantic-warning)]" />}
                  {cleanStoreName(shop.storeName)}
                  <span className={`text-xs ${activeStoreTab === idx ? 'text-white/70' : 'text-ink-subtle'}`}>
                    {shop.filteredRating.toFixed(1)}★
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* Main content */}
        {activeResult && (
          <div className="space-y-8">
            {/* 1. Store verdict - big rating + health score */}
            <StoreVerdict
              result={activeResult}
              storeName={cleanStoreName(activeResult.storeName)}
            />

            {/* 1.5. AI Store Summary */}
            {isSummaryLoading[activeStoreTab] && (
              <div className="border-t border-hairline pt-6">
                <div className="flex items-center gap-2 text-ink-subtle text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  正在生成 AI 總結...
                </div>
              </div>
            )}
            {storeSummaries[activeStoreTab] && (
              <div className="border-t border-hairline pt-6 space-y-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-primary" />
                  <h3 className="text-sm font-medium text-ink tracking-[-0.2px]">AI 總結</h3>
                </div>

                {storeSummaries[activeStoreTab].warnings.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <AlertCircle className="w-3.5 h-3.5 text-[var(--semantic-warning)]" />
                      <span className="text-xs font-medium text-[var(--semantic-warning)]">避雷提示</span>
                    </div>
                    <div className="space-y-2">
                      {storeSummaries[activeStoreTab].warnings.map((w: any, i: number) => (
                        <div key={i} className="bg-[var(--semantic-warning)]/5 border border-[var(--semantic-warning)]/15 rounded-lg p-3">
                          <p className="text-sm text-ink leading-relaxed">{w.summary}</p>
                          {w.sourceReviewIds?.length > 0 && (
                            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                              <span className="text-[11px] text-ink-tertiary">來源：</span>
                              {w.sourceReviewIds.map((id: string, j: number) => (
                                <button
                                  key={j}
                                  onClick={() => handleSourceClick(id)}
                                  className="text-[11px] text-primary hover:text-primary-hover underline underline-offset-2 cursor-pointer"
                                >
                                  {id}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {storeSummaries[activeStoreTab].recommendations.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <ThumbsUp className="w-3.5 h-3.5 text-[var(--semantic-success)]" />
                      <span className="text-xs font-medium text-[var(--semantic-success)]">推薦品項</span>
                    </div>
                    <div className="space-y-2">
                      {storeSummaries[activeStoreTab].recommendations.map((r: any, i: number) => (
                        <div key={i} className="bg-[var(--semantic-success)]/5 border border-[var(--semantic-success)]/15 rounded-lg p-3">
                          <p className="text-sm text-ink leading-relaxed">
                            <span className="font-medium">{r.item}</span>
                            {r.reason && <span className="text-ink-muted"> — {r.reason}</span>}
                          </p>
                          {r.sourceReviewIds?.length > 0 && (
                            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                              <span className="text-[11px] text-ink-tertiary">來源：</span>
                              {r.sourceReviewIds.map((id: string, j: number) => (
                                <button
                                  key={j}
                                  onClick={() => handleSourceClick(id)}
                                  className="text-[11px] text-primary hover:text-primary-hover underline underline-offset-2 cursor-pointer"
                                >
                                  {id}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {storeSummaries[activeStoreTab].warnings.length === 0 && storeSummaries[activeStoreTab].recommendations.length === 0 && (
                  <p className="text-sm text-ink-subtle">評論資料不足，無法生成總結。</p>
                )}
              </div>
            )}

            {/* 2. Rating chart - star distribution */}
            <RatingChart
              result={activeResult}
              chartId={`store-${activeStoreTab}`}
            />

            {/* 4. Review inspector - collapsed by default */}
            <ReviewInspector
              ref={inspectorRef}
              result={activeResult}
              storeIndex={activeStoreTab}
              inspectSearch={inspectSearch[activeStoreTab] || ''}
              inspectFilter={inspectFilter[activeStoreTab] || 'all'}
              onSearchChange={(val) => {
                setInspectSearch(prev => ({ ...prev, [activeStoreTab]: val }));
              }}
              onFilterChange={(val) => {
                setInspectFilter(prev => ({ ...prev, [activeStoreTab]: val }));
              }}
              expandedCoT={expandedCoT}
              onToggleCoT={toggleCoT}
            />

            {/* 5. AI QA section */}
            <div className="border-t border-hairline pt-6">
              <div className="flex items-center gap-2 mb-3">
                <MessageSquare className="w-4 h-4 text-ink-subtle" />
                <h3 className="text-sm font-medium text-ink tracking-[-0.2px]">
                  向 AI 詢問關於 {cleanStoreName(activeResult.storeName)} 的細節
                </h3>
              </div>

              <div className="flex gap-2">
                <input
                  type="text"
                  value={qaInput[activeStoreTab] || ''}
                  onChange={(e) => setQaInput(prev => ({ ...prev, [activeStoreTab]: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleQaSubmit(activeStoreTab);
                  }}
                  placeholder={hasLLMKey() ? "例如：這家店推薦點什麼菜？服務態度好嗎？" : "需要在設定頁配置 AI 模型金鑰"}
                  disabled={isQaLoading[activeStoreTab]}
                  className="flex-1 px-4 py-2 bg-surface-2 border border-hairline rounded-lg text-sm text-ink placeholder-ink-tertiary focus:outline-none focus:border-primary/50 font-sans disabled:opacity-50"
                />
                <button
                  onClick={() => handleQaSubmit(activeStoreTab)}
                  disabled={isQaLoading[activeStoreTab] || !qaInput[activeStoreTab]?.trim()}
                  className="bg-primary hover:bg-primary-hover disabled:bg-surface-3 text-white px-4 py-2 rounded-lg font-medium transition-colors cursor-pointer disabled:cursor-not-allowed flex items-center justify-center"
                >
                  {isQaLoading[activeStoreTab] ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </button>
              </div>

              {qaErrors[activeStoreTab] && (
                <div className="mt-3 p-3 bg-[var(--semantic-danger)]/10 border border-[var(--semantic-danger)]/20 text-[var(--semantic-danger)] rounded-lg text-xs font-medium flex items-center gap-2">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {qaErrors[activeStoreTab]}
                </div>
              )}

              {qaResults[activeStoreTab] && (
                <div className="mt-4 p-4 bg-surface-2 border border-hairline rounded-xl">
                  <div className="flex items-start gap-2">
                    <Sparkles className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                    <div className="flex-1 space-y-3">
                      <div className="text-sm text-ink leading-relaxed whitespace-pre-wrap">
                        {qaResults[activeStoreTab].answer}
                      </div>

                      {!qaResults[activeStoreTab].sufficient && (
                        <div className="bg-[var(--semantic-warning)]/10 border border-[var(--semantic-warning)]/20 text-[var(--semantic-warning)] text-xs p-2 rounded-lg font-medium inline-block">
                          提示：評論中可能沒有足夠的資訊回答此問題
                        </div>
                      )}

                      {qaResults[activeStoreTab].items?.length > 0 && (
                        <div className="pt-3 border-t border-hairline space-y-2 mt-2">
                          <span className="text-[11px] text-ink-subtle font-medium">
                            引用來源 (自然評論)
                          </span>
                          <div className="flex flex-col gap-2">
                            {qaResults[activeStoreTab].items.map((item: any, i: number) => {
                              const sourceReview = activeResult.auditedReviews.find(
                                r => r.username === item.id
                              );
                              return (
                                <div key={i} className="bg-surface-3 p-2.5 rounded-lg border border-hairline text-xs">
                                  <div className="flex justify-between items-center mb-1">
                                    <span className="font-medium text-ink">{item.id}</span>
                                    {sourceReview && (
                                      <span className="text-[var(--semantic-warning)] bg-[var(--semantic-warning)]/10 px-1.5 py-0.5 rounded text-[10px] border border-[var(--semantic-warning)]/20">
                                        ★ {sourceReview.stars}
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-ink-subtle mb-1.5">{item.reason}</p>
                                  {sourceReview && (
                                    <div className="bg-surface-2 p-2 rounded text-[11px] text-ink-tertiary italic border border-hairline max-h-16 overflow-y-auto">
                                      "{sourceReview.text}"
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex gap-3 justify-center pt-4 pb-2">
              <button
                onClick={() => navigate('/analyzer')}
                className="bg-primary hover:bg-primary-hover text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors cursor-pointer"
              >
                重新分析
              </button>
              <button
                onClick={() => navigate('/')}
                className="bg-surface-1 hover:bg-surface-2 text-ink-muted px-6 py-2.5 rounded-lg border border-hairline text-sm font-medium transition-colors cursor-pointer"
              >
                返回首頁
              </button>
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
