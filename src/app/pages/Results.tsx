import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate, useLocation } from 'react-router';
import { 
  ArrowLeft, Trophy, AlertTriangle, ExternalLink, Search, 
  Sparkles, Check, Loader2, ShieldCheck, HelpCircle, FileText, Activity,
  ChevronDown, ChevronUp, Star, Shield, X, Database
} from 'lucide-react';
import { RESTAURANTS_DATA } from '../data/restaurantsData';
import { parseReviews, Review } from '../utils/csvParser';
import { computeShopStats, aggregateAuditedReviews, computeSpikeMonths, getReviewTemporalContext, computeSimilaritySignals, computeHotTermSignals, computeNearbyLongReviewCounts, ShopStats, AuditResult } from '../utils/auditEngine';
import { ResponsiveContainer, BarChart, CartesianGrid, XAxis, YAxis, Tooltip, Bar } from 'recharts';

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
  
  // Safe fallback if accessed directly without selecting shops
  const storeIds = (location.state?.storeIds as string[]) || ['ramen_washed_3', 'ramen_clean_2'];

  // Base state computed from CSV data and local heuristic engine
  const [shopResults, setShopResults] = useState<ShopStats[]>([]);
  
  // Review Inspector Search & Filter states for each shop index
  const [inspectSearch, setInspectSearch] = useState<{ [key: number]: string }>({});
  const [inspectFilter, setInspectFilter] = useState<{ [key: number]: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean' }>({});

  const [isAiAuditing, setIsAiAuditing] = useState(false);
  const [aiAuditResults, setAiAuditResults] = useState<{ [storeId: string]: { [username: string]: AuditResult } }>({});
  const [apiError, setApiError] = useState('');

  // Accordion state for CoT reasoning paths (keyed by "storeIdx-reviewIdx")
  const [expandedCoT, setExpandedCoT] = useState<{ [key: string]: boolean }>({});

  // Active Store Index for detailed inspector tabs
  const [selectedInspectorTab, setSelectedInspectorTab] = useState(0);

  // Synchronized sub-metric tab state across all compared stores
  const [activeSubTab, setActiveSubTab] = useState<'rating' | 'anomalies' | 'charts'>('rating');

  // Active store tab selected in the top switcher navbar ('all' or storeIndex)
  const [activeStoreTab, setActiveStoreTab] = useState<number | 'all'>('all');

  // Two-Stage Pipeline Logs State
  interface PipelineLog {
    storeId: string;
    storeName: string;
    totalReviews: number;
    stage1Count: number; // Regex flagged
    stage2Sent: number;   // Ambiguous sent to Gemini
    stage2Flagged: number; // Gemini flagged
    stage2Passed: number;  // Gemini passed
  }
  const [pipelineLogs, setPipelineLogs] = useState<PipelineLog[]>([]);

  // 1. Initial Parse and Compute local heuristics
  useEffect(() => {
    const customShops = (location.state?.customShops as Array<{ id: string; name: string; reviews: Review[] }>) || [];

    let computed: ShopStats[] = [];
    if (customShops.length > 0) {
      computed = customShops.map(shop => {
        return computeShopStats(shop.name, shop.reviews);
      });
    } else {
      const activeIds = storeIds.length > 0 ? storeIds : ['ramen_washed_3', 'ramen_clean_2'];
      computed = activeIds.map(id => {
        const store = RESTAURANTS_DATA.find(r => r.id === id);
        if (!store) return null;
        const reviews = parseReviews(store.csvContent);
        return computeShopStats(store.name, reviews);
      }).filter(Boolean) as ShopStats[];
    }
    
    setShopResults(computed);
    
    // Initialize search & filter states
    const initialSearch: { [key: number]: string } = {};
    const initialFilter: { [key: number]: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean' } = {};
    computed.forEach((_, idx) => {
      initialSearch[idx] = '';
      initialFilter[idx] = 'all';
    });
    setInspectSearch(initialSearch);
    setInspectFilter(initialFilter);
  }, [location.state?.storeIds, location.state?.customShops]);

  // 1.5. Auto-trigger AI Audit on mount once shopResults are computed
  useEffect(() => {
    if (shopResults.length > 0 && !isAiAuditing && Object.keys(aiAuditResults).length === 0) {
      handleGeminiAudit(shopResults);
    }
  }, [shopResults]);

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
        const id = storeIds[idx] || `custom_${idx}`;
        const reviews = result.auditedReviews;

        const spikeMonths = computeSpikeMonths(reviews);
        const getReviewTemporalData = (r: Review) => getReviewTemporalContext(r, spikeMonths, new Date('2026-05-19'));

        // Precomputed cross-review signals, aligned by index to `reviews`, fed
        // to Gemini as context (not used to auto-decide a verdict here).
        const similaritySignals = computeSimilaritySignals(reviews);
        const hotTermSignals = computeHotTermSignals(reviews);
        const nearbyLongReviewCounts = computeNearbyLongReviewCounts(reviews);

        // Stage 1 already reached a confident verdict (incentive/template/
        // no_text/low_info) for anything with a non-null issueType — re-litigating
        // those via Gemini would be wasteful and could silently override a
        // deliberate local rule (e.g. low_info) with a worse LLM guess. Only
        // genuinely ambiguous 5-star reviews (issueType === null) go to Stage 2.
        const stage1Count = reviews.filter(r => r.stars === 5 && r.audit.issueType !== null).length;

        const ambiguousReviews = reviews.filter(r => r.stars === 5 && r.audit.issueType === null);

        // No sampling cap — every ambiguous 5-star review with text gets sent for
        // Stage 2 review; the backend splits them into batches itself.
        const stage2Sent = ambiguousReviews.length;

        let stage2Flagged = 0;
        let stage2Passed = 0;
        const storeMap: { [username: string]: AuditResult } = {};

        if (stage2Sent > 0) {
          const reviewsPayload = ambiguousReviews.map(r => {
            const { isSpikePeriod, daysElapsed } = getReviewTemporalData(r);
            const idx = reviews.indexOf(r);
            const { maxSimilarity, similarCount } = similaritySignals[idx];
            const { hotTermCount, hotTermMaxRatio } = hotTermSignals[idx];
            return {
              username: r.username,
              text: r.text,
              stars: r.stars,
              images: r.images,
              daysElapsed,
              isSpikePeriod,
              maxSimilarity,
              similarCount,
              hotTermCount,
              hotTermMaxRatio,
              nearbyLongReviewCount: nearbyLongReviewCounts[idx]
            };
          });

          const response = await fetch('/api/audit', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              storeName: result.storeName,
              reviews: reviewsPayload
            })
          });

          if (!response.ok) {
            const errData = await response.json().catch(() => null);
            throw new Error(errData?.error || (errData?.details || []).join('; ') || '後端 AI 語意審計請求失敗');
          }

          const responseJson = await response.json();
          const items: any[] = responseJson.results || [];

          items.forEach(item => {
            if (item.isWashed) {
              stage2Flagged++;
            } else {
              stage2Passed++;
            }

            const inc = item.incentiveIntensity || 3;
            const aut = item.sentimentAuthenticity || 3;
            const gra = item.descriptionGranularity || 3;

            // S_val: 0 (dimensions read as clean) .. 12 (dimensions read as washed),
            // independent of the model's own isWashed call.
            const sVal = (inc - 1) + (5 - aut) + (5 - gra);
            const washRatio = sVal / 12;

            // agreement: how strongly the I/A/D dimensions back up the model's binary
            // verdict. 1 = fully backed, 0 = fully contradicted, 0.5 = genuinely
            // ambiguous (dimensions don't lean either way — this is also what you get
            // when the model omits the dimension scores, since they default to 3/3/3).
            const agreement = item.isWashed ? washRatio : (1 - washRatio);

            // Full 0-100 range. The ^1.5 curve pulls the ambiguous midpoint
            // (agreement=0.5) down to ~35% instead of pinning it at 50+/60+, so a low
            // number visibly reads as "treat this verdict with caution" rather than
            // looking like moderate confidence.
            let confidence = Math.round(Math.pow(agreement, 1.5) * 100);
            confidence = Math.max(0, Math.min(100, confidence));

            storeMap[item.username] = {
              isWashed: item.isWashed,
              reason: item.reason,
              confidenceScore: confidence,
              issueType: item.issueType === 'none' ? null : (item.issueType as any),
              reasoningPath: item.reasoningPath,
              incentiveIntensity: inc,
              sentimentAuthenticity: aut,
              descriptionGranularity: gra
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
        const matchingId = storeIds[idx] || `custom_${idx}`;

        if (!newAiResults[matchingId]) return shop;

        const aiStoreMap = newAiResults[matchingId];

        const updatedReviews = shop.auditedReviews.map(r => {
          // Reviews Stage 1 already reached a confident verdict on were never
          // sent to Gemini — keep their original Stage 1 audit untouched
          // rather than accepting an aiStoreMap entry that shouldn't exist
          // for them (or silently losing the verdict).
          if (r.audit.issueType !== null) {
            return r;
          }

          if (aiStoreMap[r.username]) {
            return {
              ...r,
              audit: aiStoreMap[r.username]
            };
          }

          return r;
        });

        // Re-aggregate through the same shared formula computeShopStats used for the
        // Stage-1-only pass, instead of recomputing the weighting/Trust Score math here.
        return aggregateAuditedReviews(shop.storeName, updatedReviews);
      });

      setShopResults(updatedResults);
    } catch (e: any) {
      console.error(e);
      setApiError(e.message || '連線 API 時發生未知錯誤');
    } finally {
      setIsAiAuditing(false);
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

  // Early return while loading to prevent partial flashing
  if (!isComplete) {
    return (
      <div className="min-h-screen bg-[#f5f1e8] flex flex-col font-sans selection:bg-[#6b8e7f]/20">
        <header className="sticky top-0 z-50 backdrop-blur-md bg-[#f5f1e8]/80 border-b border-[#d4c5b0]/30 px-4 md:px-8 py-3.5 flex items-center justify-between shadow-xs">
          <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
            <div className="bg-[#6b8e7f] text-white w-9 h-9 rounded-xl border-2 border-[#4a5d52] font-black text-base shadow-sm flex items-center justify-center">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <span className="font-display font-black text-lg text-[#4a5d52] tracking-tight">
              疑騙真星 <span className="text-[#6b8e7f] font-sans font-bold text-sm bg-white border border-[#d4c5b0]/60 px-1.5 py-0.5 rounded-md ml-1">TrueRating</span>
            </span>
          </div>
          <button
            onClick={() => navigate('/analyzer')}
            className="flex items-center gap-1.5 bg-white px-4 py-1.5 rounded-full shadow-xs border border-[#d4c5b0] text-xs font-bold text-[#4a5d52] cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4 text-[#6b8e7f]" />
            返回修改
          </button>
        </header>

        <div className="flex-1 flex flex-col items-center justify-center p-4 md:p-8">
          {showLoader && shopResults.length > 0 ? (
            <div className="max-w-5xl w-full grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
              {/* Left Column: Loader */}
              <div className="lg:col-span-5 flex justify-center">
                <motion.div
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-[32px] p-6 shadow-md border-2 border-[#6b8e7f] flex flex-col items-center justify-center text-center relative overflow-hidden w-full"
                >
                  <div className="absolute left-0 right-0 h-1 bg-[#6b8e7f]/50 top-0 animate-scan shadow-[0_0_10px_#6b8e7f]"></div>
                  
                  <Loader2 className="w-10 h-10 animate-spin text-[#6b8e7f] mb-4" />
                  <h3 className="font-extrabold text-base text-[#4a5d52] mb-1.5 font-display">
                    雙階段 AI 混合審計進行中...
                  </h3>
                  <p className="text-xs text-[#6b8e7f] max-w-xs mb-6 font-medium leading-relaxed">
                    系統正執行「啟發式正則篩選 ➔ AI 語意矛盾檢索 ➔ 大模型思維鏈推理」，這大約需要數秒。
                  </p>

                  <div className="w-full space-y-2 bg-[#f5f1e8]/50 p-4 rounded-xl border border-[#d4c5b0]/60 text-left text-xs font-bold text-[#4a5d52]">
                    <div className="flex items-center gap-2">
                      <span className="text-[#6b8e7f] font-bold">✓</span>
                      <span>階段一：本地正則規則匹配</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[#6b8e7f] font-bold">✓</span>
                      <span>階段一：時間發布異常密度計算</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#6b8e7f] opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-[#6b8e7f]"></span>
                      </span>
                      <span className="text-[#6b8e7f]">階段二：調用大語言模型語意複審中...</span>
                    </div>
                  </div>
                </motion.div>
              </div>

              {/* Right Column: Stage 1 Report */}
              <div className="lg:col-span-7 bg-white rounded-[32px] p-6 shadow-md border border-[#d4c5b0]/60 space-y-5">
                <h3 className="font-extrabold text-base text-[#4a5d52] border-b border-[#d4c5b0]/40 pb-3 flex items-center gap-2 font-display">
                  <Database className="w-5 h-5 text-[#6b8e7f]" />
                  第一階段：本機啟發式規則分析報告 (已完成)
                </h3>
                <div className="space-y-4">
                  {shopResults.map((shop, idx) => {
                    const reviews = shop.auditedReviews || shop.reviews || [];
                    const stage1Washed = reviews.filter(r => r.audit.issueType !== null);
                    const stage1Count = stage1Washed.length;

                    const ambiguousReviews = reviews.filter(r => r.stars === 5 && r.audit.issueType === null);

                    const stage2Sent = ambiguousReviews.length;

                    const remainingReviews = reviews.filter(r => r.audit.issueType === null);
                    const heuristicRating = remainingReviews.length > 0
                      ? Number((remainingReviews.reduce((sum, r) => sum + r.stars, 0) / remainingReviews.length).toFixed(2))
                      : shop.originalRating;

                    return (
                      <div key={idx} className="bg-[#f5f1e8]/40 p-4 rounded-2xl border border-[#d4c5b0]/60 space-y-4">
                        <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-2">
                          <div>
                            <h4 className="font-extrabold text-[#4a5d52] text-sm flex items-center gap-1.5">
                              <span className="inline-block w-2.5 h-2.5 rounded-md bg-[#6b8e7f]"></span>
                              {cleanStoreName(shop.storeName)}
                            </h4>
                            <p className="text-[10px] text-[#6b8e7f] mt-0.5 font-bold">總評論數量：{shop.totalReviews} 則</p>
                          </div>
                          
                          <div className="flex items-center gap-3 bg-white/40 px-3 py-1.5 rounded-xl border border-[#d4c5b0]/20 self-start sm:self-auto">
                            <div className="text-right">
                              <div className="text-[9px] text-[#6b8e7f] font-bold">原始評分</div>
                              <div className="text-xs font-black text-[#4a5d52]/60 line-through">{shop.originalRating.toFixed(1)} ★</div>
                            </div>
                            <div className="h-6 w-[1px] bg-[#d4c5b0]/60"></div>
                            <div className="text-right">
                              <div className="text-[9px] text-[#6b8e7f] font-bold">一階篩後評分</div>
                              <div className="text-sm font-black text-[#6b8e7f]">{heuristicRating.toFixed(2)} ★</div>
                            </div>
                          </div>
                        </div>

                        {/* Heuristic indicators grid */}
                        <div className="grid grid-cols-3 gap-2.5 pt-3 border-t border-[#d4c5b0]/30 text-center">
                          <div className="bg-white/60 p-2 rounded-xl border border-[#d4c5b0]/40">
                            <div className="text-[9px] text-[#6b8e7f] font-bold">一階正則洗評</div>
                            <div className="text-xs font-black text-red-500 mt-0.5">{stage1Count} 則</div>
                          </div>
                          <div className="bg-white/60 p-2 rounded-xl border border-[#d4c5b0]/40">
                            <div className="text-[9px] text-[#6b8e7f] font-bold">二階 AI 待審</div>
                            <div className="text-xs font-black text-amber-500 mt-0.5">{stage2Sent} 則</div>
                          </div>
                          <div className="bg-white/60 p-2 rounded-xl border border-[#d4c5b0]/40 flex flex-col justify-center items-center">
                            <div className="text-[9px] text-[#6b8e7f] font-bold">當前進度</div>
                            <div className="text-[9px] font-black text-[#6b8e7f] mt-0.5 flex items-center justify-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
                              AI 審查中
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center bg-white p-8 rounded-[32px] border border-[#d4c5b0] max-w-sm shadow-md">
              <Loader2 className="w-8 h-8 animate-spin text-[#6b8e7f] mx-auto mb-3" />
              <p className="text-xs text-[#6b8e7f] font-bold">正在讀取評價數據集庫，請稍候...</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  const gridLayoutClass = shopResults.length === 1 
    ? 'grid-cols-1 max-w-2xl mx-auto' 
    : shopResults.length === 2 
    ? 'grid-cols-1 lg:grid-cols-2 max-w-5xl' 
    : 'grid-cols-1 lg:grid-cols-3 max-w-7xl';

  return (
    <div className="min-h-screen bg-[#f5f1e8] font-sans selection:bg-[#6b8e7f]/20 pb-16">
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
        <button
          onClick={() => navigate('/analyzer')}
          className="flex items-center gap-1.5 bg-white px-4 py-1.5 rounded-full shadow-xs border border-[#d4c5b0] text-xs font-bold text-[#4a5d52] cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4 text-[#6b8e7f]" />
          返回修改
        </button>
      </header>

      <div className="container mx-auto px-4 py-8 max-w-7xl">
        {apiError && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-8 p-4 bg-[#fde8e8] border-3 border-[#e53e3e] text-[#9b2c2c] rounded-2xl shadow-[4px_4px_0px_0px_#9b2c2c] max-w-4xl mx-auto flex items-start gap-3"
          >
            <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5 text-[#e53e3e]" />
            <div className="flex-1 space-y-1">
              <p className="font-extrabold text-sm font-sans">第二階段 AI 語意審計失敗：</p>
              <p className="text-xs font-semibold leading-relaxed">{apiError}</p>
            </div>
            <button
              onClick={() => setApiError('')}
              className="text-[#9b2c2c] hover:opacity-80 font-black cursor-pointer ml-2"
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
        
        {/* Sleek Tactile Shop Switcher Navbar */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-wrap gap-2.5 p-2 bg-white rounded-2xl mb-8 border-3 border-[#4a5d52] shadow-tactile max-w-4xl mx-auto justify-center select-none"
        >
          <button
            onClick={() => {
              setActiveStoreTab('all');
              setSelectedInspectorTab(0);
            }}
            className={`px-4 py-2.5 rounded-xl text-xs md:text-sm font-black transition-all cursor-pointer flex items-center gap-1.5 border-2 active:translate-y-0.5 active:shadow-none ${
              activeStoreTab === 'all'
                ? 'bg-[#6b8e7f] text-white border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52]'
                : 'bg-white text-[#4a5d52] border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] hover:bg-[#6b8e7f]/10'
            }`}
          >
            <Activity className="w-4 h-4" />
            全部對比 ({shopResults.length} 間)
          </button>
          
          {shopResults.map((shop, idx) => {
            const isBest = idx === bestStoreIndex && shopResults.length > 1;
            return (
              <button
                key={idx}
                onClick={() => {
                  setActiveStoreTab(idx);
                  setSelectedInspectorTab(idx);
                }}
                className={`px-4 py-2.5 rounded-xl text-xs md:text-sm font-black transition-all cursor-pointer flex items-center gap-2 border-2 active:translate-y-0.5 active:shadow-none ${
                  activeStoreTab === idx
                    ? 'bg-[#6b8e7f] text-white border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52]'
                    : 'bg-white text-[#4a5d52] border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] hover:bg-[#6b8e7f]/10'
                }`}
              >
                {isBest && <Trophy className="w-3.5 h-3.5 text-[#e8c547] fill-[#e8c547]" />}
                <span>{cleanStoreName(shop.storeName)} {shop.filteredRating.toFixed(1)}★</span>
              </button>
            );
          })}
        </motion.div>

        {/* Global Synchronized Sub-Metric Switcher */}
        <div className="flex gap-2 p-1.5 bg-[#f5f1e8] rounded-2xl mb-8 border-2 border-[#4a5d52] max-w-sm mx-auto shadow-[4px_4px_0px_0px_#4a5d52] select-none">
          <button
            onClick={() => setActiveSubTab('rating')}
            className={`flex-1 py-2.5 rounded-xl text-xs font-black transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
              activeSubTab === 'rating'
                ? 'bg-[#6b8e7f] text-white shadow-[2px_2px_0px_0px_#4a5d52] border-2 border-[#4a5d52]'
                : 'text-[#6b8e7f] hover:text-[#4a5d52] border-2 border-transparent hover:bg-white/50'
            }`}
          >
            <Star className="w-4 h-4" />
            評分脫水
          </button>
          <button
            onClick={() => setActiveSubTab('anomalies')}
            className={`flex-1 py-2.5 rounded-xl text-xs font-black transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
              activeSubTab === 'anomalies'
                ? 'bg-[#6b8e7f] text-white shadow-[2px_2px_0px_0px_#4a5d52] border-2 border-[#4a5d52]'
                : 'text-[#6b8e7f] hover:text-[#4a5d52] border-2 border-transparent hover:bg-white/50'
            }`}
          >
            <AlertTriangle className="w-4 h-4" />
            灌水特徵
          </button>
          <button
            onClick={() => setActiveSubTab('charts')}
            className={`flex-1 py-2.5 rounded-xl text-xs font-black transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
              activeSubTab === 'charts'
                ? 'bg-[#6b8e7f] text-white shadow-[2px_2px_0px_0px_#4a5d52] border-2 border-[#4a5d52]'
                : 'text-[#6b8e7f] hover:text-[#4a5d52] border-2 border-transparent hover:bg-white/50'
            }`}
          >
            <FileText className="w-4 h-4" />
            星級分布
          </button>
        </div>

        {/* Multi-Column Side-by-Side Grid Layout */}
        <div className={`grid gap-6 ${
          activeStoreTab === 'all' ? gridLayoutClass : 'grid-cols-1 max-w-2xl mx-auto'
        }`}>
          {shopResults
            .map((result, idx) => ({ result, idx }))
            .filter(({ idx }) => activeStoreTab === 'all' || activeStoreTab === idx)
            .map(({ result, idx }) => {
              const isBest = idx === bestStoreIndex && shopResults.length > 1;
              const hasMajorDrop = result.originalRating - result.filteredRating >= 0.3 || result.trustScore < 80;
            
            const distData = [
              { star: '5★', '原始評價': result.ratingDistribution.original[5] || 0, '濾水真實': result.ratingDistribution.filtered[5] || 0 },
              { star: '4★', '原始評價': result.ratingDistribution.original[4] || 0, '濾水真實': result.ratingDistribution.filtered[4] || 0 },
              { star: '3★', '原始評價': result.ratingDistribution.original[3] || 0, '濾水真實': result.ratingDistribution.filtered[3] || 0 },
              { star: '2★', '原始評價': result.ratingDistribution.original[2] || 0, '濾水真實': result.ratingDistribution.filtered[2] || 0 },
              { star: '1★', '原始評價': result.ratingDistribution.original[1] || 0, '濾水真實': result.ratingDistribution.filtered[1] || 0 },
            ];

            return (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 + idx * 0.1 }}
                className={`bg-white rounded-[32px] overflow-hidden border-3 flex flex-col justify-between transition-all duration-300 hover:-translate-y-1 ${
                  isBest ? 'border-[#e8c547] shadow-[4px_4px_0px_0px_#e8c547] ring-4 ring-[#e8c547]/10' : 'border-[#4a5d52] shadow-[4px_4px_0px_0px_#4a5d52]'
                }`}
              >
                {/* Store Header Banner */}
                <div className={`px-4.5 py-4 ${
                  isBest ? 'bg-[#e8c547]' : 'bg-[#6b8e7f]'
                } border-b-3 border-[#4a5d52] flex items-center justify-between`}>
                  <div className="truncate">
                    <h2 className="text-sm md:text-base font-black flex items-center gap-1.5 text-[#4a5d52] font-display truncate">
                      {isBest && <Trophy className="w-4 h-4 text-[#4a5d52]" />}
                      {cleanStoreName(result.storeName)}
                    </h2>
                    <p className="text-[9px] text-[#4a5d52]/80 font-bold tracking-wider">
                      載入 {result.totalReviews} 則歷史評論
                    </p>
                  </div>
                  <div className="bg-white/40 border border-[#4a5d52]/60 px-2 py-0.5 rounded-full text-[9px] font-black text-[#4a5d52] shrink-0 ml-1">
                    {result.trustScore >= 75 ? '安全信譽' : result.trustScore >= 50 ? '警告標記' : '高危洗評'}
                  </div>
                </div>

                {/* Body Content - Switched based on activeSubTab with fixed min height */}
                <div className="p-4.5 space-y-4 flex-1 flex flex-col justify-between min-h-[300px]">
                  <AnimatePresence mode="wait">
                    {activeSubTab === 'rating' && (
                      <motion.div
                        key="rating"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        className="space-y-4 flex-1 flex flex-col justify-between"
                      >
                        {/* Rating Drop Visual Flowcard */}
                        <div className="space-y-3">
                          <h4 className="text-[10px] font-black text-[#4a5d52] uppercase tracking-wider border-b border-[#d4c5b0]/40 pb-1 flex justify-between items-center font-display">
                            <span>星級評分脫水流程</span>
                            {hasMajorDrop && (
                              <span className="bg-[#d4a5a5] text-[#8c4848] px-1.5 py-0.5 rounded text-[8px] font-sans font-extrabold animate-pulse">
                                評分水分重
                              </span>
                            )}
                          </h4>

                          <div className="bg-[#f5f1e8]/70 border border-[#d4c5b0]/60 p-2.5 rounded-xl flex items-center justify-around text-center">
                            <div>
                              <span className="block text-[8px] text-[#6b8e7f] font-bold">原始</span>
                              <span className="text-sm font-black text-[#4a5d52]">{result.originalRating.toFixed(2)}★</span>
                            </div>
                            <div className="text-xs text-[#d4c5b0] font-black">➔</div>
                            <div>
                              <span className="block text-[8px] text-[#8c4848] font-bold">扣減</span>
                              <span className="text-xs font-black text-[#8c4848]">
                                -{(result.originalRating - result.filteredRating).toFixed(2)}★
                              </span>
                            </div>
                            <div className="text-xs text-[#d4c5b0] font-black">➔</div>
                            <div>
                              <span className="block text-[8px] text-[#6b8e7f] font-bold">真實</span>
                              <span className="text-sm font-black text-[#6b8e7f]">{result.filteredRating.toFixed(2)}★</span>
                            </div>
                          </div>
                        </div>

                        {/* Explanation Text */}
                        <div className="text-[10px] leading-relaxed text-[#4a5d52] mt-3">
                          {result.trustScore < 80 ? (
                            <div className="bg-[#d4a5a5]/10 border border-[#d4a5a5]/25 p-3 rounded-lg text-[#8c4848] font-semibold leading-relaxed">
                              系統過濾虛假 5 星洗評後，真實得分降至 <b>{result.filteredRating.toFixed(2)}★</b>，存在灌水引導嫌疑。
                            </div>
                          ) : (
                            <div className="bg-[#6b8e7f]/10 border border-[#6b8e7f]/25 p-3 rounded-lg text-[#304a3e] font-semibold leading-relaxed">
                              評分多為自然就餐生成，無刻意洗評痕跡，真實口碑約 <b>{result.filteredRating.toFixed(2)}★</b>。
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}

                    {activeSubTab === 'anomalies' && (
                      <motion.div
                        key="anomalies"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        className="space-y-4 flex-1 flex flex-col justify-between"
                      >
                        {/* Trust Score Box */}
                        <div className="bg-[#f5f1e8]/30 rounded-xl p-3.5 border border-[#d4c5b0]/60">
                          <div className="flex justify-between items-center text-[10px] font-black text-[#6b8e7f] mb-1">
                            <span className="flex items-center gap-1">
                              <ShieldCheck className="w-3.5 h-3.5" />
                              真實信任度分數
                            </span>
                            <span className="text-xs font-black text-[#4a5d52]">{result.trustScore}/100</span>
                          </div>
                          <div className="w-full bg-[#e8dcc8]/60 h-2.5 rounded-full overflow-hidden mb-1.5">
                            <div 
                              className={`h-full rounded-full transition-all duration-500 ${
                                result.trustScore >= 75 ? 'bg-[#6b8e7f]' : result.trustScore >= 50 ? 'bg-[#e8c547]' : 'bg-[#d4a5a5]'
                              }`}
                              style={{ width: `${result.trustScore}%` }}
                            ></div>
                          </div>
                          <p className="text-[9px] text-[#6b8e7f] font-semibold">
                            偵測到 {result.suspiciousReviews} 則疑似洗評（約佔總數的 {result.totalReviews > 0 ? ((result.suspiciousReviews / result.totalReviews) * 100).toFixed(0) : 0}%）
                          </p>
                        </div>

                        {/* Feature anomaly list */}
                        <div className="space-y-2">
                          <span className="block text-[8px] text-[#6b8e7f] font-bold uppercase tracking-wider">
                            洗評異常特徵計數：
                          </span>
                          <div className="grid grid-cols-3 gap-2">
                            <div className="bg-white rounded-lg p-2.5 border border-[#d4c5b0]/60 text-center shadow-2xs">
                              <span className="block text-sm font-black text-[#8c4848]">{result.issues.timeAnomaly}</span>
                              <span className="text-[8px] text-[#6b8e7f] font-bold">打卡促銷</span>
                            </div>
                            <div className="bg-white rounded-lg p-2.5 border border-[#d4c5b0]/60 text-center shadow-2xs">
                              <span className="block text-sm font-black text-[#8b7534]">{result.issues.templateText}</span>
                              <span className="text-[8px] text-[#6b8e7f] font-bold">極短模版</span>
                            </div>
                            <div className="bg-white rounded-lg p-2.5 border border-[#d4c5b0]/60 text-center shadow-2xs">
                              <span className="block text-sm font-black text-[#6b8e7f]">{result.issues.vague}</span>
                              <span className="text-[8px] text-[#6b8e7f] font-bold">語意衝突</span>
                            </div>
                          </div>
                        </div>
                      </motion.div>
                    )}

                    {activeSubTab === 'charts' && (
                      <motion.div
                        key="charts"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        className="space-y-4 flex-1 flex flex-col justify-center"
                      >
                        {/* Star Distribution chart */}
                        <div className="bg-white rounded-xl p-2.5 border border-[#e8dcc8]">
                          <h5 className="text-[9px] font-black text-[#4a5d52] uppercase tracking-wider mb-2 font-display">
                            星級分佈對比（原始 vs 濾水）
                          </h5>
                          <div className="h-44 w-full">
                            <ResponsiveContainer width="100%" height="100%">
                              <BarChart data={distData} margin={{ top: 5, right: 5, left: -32, bottom: 5 }}>
                                <defs>
                                  <linearGradient id={`colorOriginal-${idx}`} x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#e8c547" stopOpacity={0.95}/>
                                    <stop offset="95%" stopColor="#d5b22b" stopOpacity={0.6}/>
                                  </linearGradient>
                                  <linearGradient id={`colorFiltered-${idx}`} x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#6b8e7f" stopOpacity={0.95}/>
                                    <stop offset="95%" stopColor="#4a5d52" stopOpacity={0.6}/>
                                  </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e8dcc8" />
                                <XAxis dataKey="star" tick={{ fontSize: 8, fill: '#4a5d52', fontWeight: 'bold' }} stroke="#d4c5b0" />
                                <YAxis tick={{ fontSize: 8, fill: '#4a5d52' }} stroke="#d4c5b0" />
                                <Tooltip 
                                  contentStyle={{ backgroundColor: 'white', borderRadius: '10px', border: '1.5px solid #d4c5b0', fontSize: '9px', fontWeight: 'bold' }}
                                />
                                <Bar dataKey="原始評價" fill={`url(#colorOriginal-${idx})`} radius={[3, 3, 0, 0]} />
                                <Bar dataKey="濾水真實" fill={`url(#colorFiltered-${idx})`} radius={[3, 3, 0, 0]} />
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

              </motion.div>
            );
          })}
        </div>

        {/* Tabbed Detailed Review Inspector (Bottom Layout Card) */}
        {shopResults.length > 0 && shopResults[selectedInspectorTab] && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="bg-white rounded-[32px] border-3 border-[#4a5d52] shadow-tactile overflow-hidden mt-10 max-w-5xl mx-auto"
          >
            {/* Inspector Navigation Header & Tabs */}
            <div className="bg-[#f5f1e8] p-5 border-b-3 border-[#4a5d52] flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1.5">
                <span className="text-xs font-black text-[#4a5d52] uppercase tracking-wider flex items-center gap-1.5 font-display">
                  <Search className="w-4 h-4 text-[#6b8e7f]" />
                  店家歷史評價內容透視與審計日誌
                </span>
                {/* Store selection tabs */}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {shopResults.map((shop, sIdx) => (
                    <button
                      key={sIdx}
                      onClick={() => setSelectedInspectorTab(sIdx)}
                      className={`px-3 py-1.5 rounded-xl text-xs font-black transition-all cursor-pointer active:translate-y-0.5 active:shadow-none ${
                        selectedInspectorTab === sIdx
                          ? 'bg-[#6b8e7f] text-white shadow-[2px_2px_0px_0px_#4a5d52] border-2 border-[#4a5d52]'
                          : 'bg-white text-[#4a5d52] border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] hover:bg-[#6b8e7f]/10 hover:-translate-y-0.5'
                      }`}
                    >
                      {cleanStoreName(shop.storeName)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Inspector query filters */}
              {(() => {
                const result = shopResults[selectedInspectorTab];
                return (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={inspectSearch[selectedInspectorTab] || ''}
                      onChange={(e) => {
                        const newSearch = { ...inspectSearch };
                        newSearch[selectedInspectorTab] = e.target.value;
                        setInspectSearch(newSearch);
                      }}
                      placeholder="搜尋評論關鍵字..."
                      className="px-3 py-1 bg-white rounded-lg border border-[#d4c5b0] text-[11px] text-[#4a5d52] focus:outline-none focus:border-[#6b8e7f] placeholder-[#a0b3a0] w-36 shadow-xs font-semibold"
                    />

                    {(() => {
                      const stage1Count = result.auditedReviews.filter(r => r.audit.isWashed && !r.audit.reasoningPath).length;
                      const stage2Count = result.auditedReviews.filter(r => r.audit.isWashed && r.audit.reasoningPath).length;
                      return (
                        <select
                          value={inspectFilter[selectedInspectorTab] || 'all'}
                          onChange={(e) => {
                            const newFilters = { ...inspectFilter };
                            newFilters[selectedInspectorTab] = e.target.value as 'all' | 'washed' | 'stage1' | 'stage2' | 'clean';
                            setInspectFilter(newFilters);
                          }}
                          className="bg-white border border-[#d4c5b0] rounded-lg px-2 py-1 text-[11px] font-extrabold text-[#4a5d52] shadow-xs cursor-pointer"
                        >
                          <option value="all">顯示全部 ({result.totalReviews})</option>
                          <option value="washed">所有灌水洗評 ({result.suspiciousReviews})</option>
                          <option value="stage1">僅看一階規則攔截 ({stage1Count})</option>
                          <option value="stage2">僅看二階 AI 攔截 ({stage2Count})</option>
                          <option value="clean">僅看真實評論 ({result.totalReviews - result.suspiciousReviews})</option>
                        </select>
                      );
                    })()}
                  </div>
                );
              })()}
            </div>

            {/* Pipeline Logs display matching the selected store */}
            {(() => {
              const activeShop = shopResults[selectedInspectorTab];
              const storeLog = pipelineLogs.find(log => log.storeName === activeShop.storeName);
              if (!storeLog) return null;
              return (
                <div className="bg-[#f5f1e8]/60 p-4 border-b border-[#d4c5b0]/40 text-[11px] text-[#4a5d52] space-y-2">
                  <span className="font-extrabold text-[#4a5d52] uppercase tracking-wider block font-display">
                    {cleanStoreName(activeShop.storeName)} 雙階段審計流水線日誌
                  </span>
                  
                  <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 pt-1">
                    <div className="flex-1 bg-white border border-[#d4c5b0]/60 p-2.5 rounded-lg flex justify-between items-center shadow-xs">
                      <span className="text-[#6b8e7f] font-bold">1. 歷史載入</span>
                      <span className="font-black text-[#4a5d52]">{storeLog.totalReviews} 則</span>
                    </div>

                    <div className="text-center font-bold text-[#d4c5b0] text-[10px] md:block hidden">➔</div>
                    <div className="text-center font-bold text-[#d4c5b0] text-[10px] md:hidden block">▼</div>

                    <div className="flex-1 bg-[#d4a5a5]/10 border border-[#d4a5a5]/30 p-2.5 rounded-lg flex justify-between items-center text-[#8c4848] shadow-xs">
                      <span className="font-bold flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#8c4848] animate-pulse"></span>
                        2. 規則攔截
                      </span>
                      <span className="font-black">{storeLog.stage1Count} 則</span>
                    </div>

                    <div className="text-center font-bold text-[#d4c5b0] text-[10px] md:block hidden">➔</div>
                    <div className="text-center font-bold text-[#d4c5b0] text-[10px] md:hidden block">▼</div>

                    <div className="flex-1 bg-white border border-[#d4c5b0]/60 p-2.5 rounded-lg flex justify-between items-center shadow-xs">
                      <span className="font-bold text-[#6b8e7f]">3. AI 語意複審</span>
                      <div className="flex gap-1.5 items-center font-black">
                        <span>送 {storeLog.stage2Sent} 則</span>
                        {storeLog.stage2Sent > 0 && (
                          <span className="text-[9px] bg-[#d4a5a5]/20 text-[#8c4848] px-1 py-0.5 rounded font-black">
                            洗評:{storeLog.stage2Flagged}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}

            {/* Scrollable list of reviews of the selected store */}
            {(() => {
              const activeShop = shopResults[selectedInspectorTab];
              const query = inspectSearch[selectedInspectorTab] || '';
              const filter = inspectFilter[selectedInspectorTab] || 'all';
              
              const filteredReviews = activeShop.auditedReviews.filter(rev => {
                const textMatch = rev.text.toLowerCase().includes(query.toLowerCase()) || rev.username.toLowerCase().includes(query.toLowerCase());
                if (!textMatch) return false;

                if (filter === 'washed') return rev.audit.isWashed;
                if (filter === 'stage1') return rev.audit.isWashed && !rev.audit.reasoningPath;
                if (filter === 'stage2') return rev.audit.isWashed && !!rev.audit.reasoningPath;
                if (filter === 'clean') return !rev.audit.isWashed;
                return true;
              });

              return (
                <div className="divide-y divide-[#f5f1e8] max-h-96 overflow-y-auto bg-white p-2">
                  {filteredReviews.length === 0 ? (
                    <div className="text-center py-12 text-xs text-[#6b8e7f] font-bold">
                      無符合篩選或關鍵字搜尋條件的評價內容。
                    </div>
                  ) : (
                    filteredReviews.map((review, rIdx) => {
                      const isWashed = review.audit.isWashed;
                      const isLowInfo = review.audit.issueType === 'low_info';
                      // Below 50% confidence, "isWashed: true" is a weak signal, not a
                      // confirmed catch — read the label/color/chip as tentative rather
                      // than the same certainty as a high-confidence interception.
                      const isLowConfidenceWashed = isWashed && review.audit.confidenceScore < 50;
                      const hasCoT = !!review.audit.reasoningPath;
                      const cotExpanded = expandedCoT[`${selectedInspectorTab}-${rIdx}`];

                      return (
                        <div key={rIdx} className="p-3 text-[11px] flex flex-col gap-2 hover:bg-[#f5f1e8]/30 rounded-xl transition-colors">
                          <div className="flex items-center justify-between">
                            <span className="font-extrabold text-[#4a5d52]">{review.username}</span>
                            <div className="flex items-center gap-2">
                              <span className="text-[#6b8e7f] text-[9px] font-medium">{review.time}</span>
                              <span className="font-bold text-[#e8c547] bg-[#e8c547]/10 px-2 py-0.5 rounded-full border border-[#e8c547]/30 text-[9px]">
                                ★ {review.stars}
                              </span>
                            </div>
                          </div>
                          <p className="text-[#4a5d52] leading-relaxed whitespace-pre-wrap font-medium">{review.text}</p>
                          
                          {/* Audit Status Box */}
                          {isWashed ? (
                            <div className={isLowConfidenceWashed
                              ? "bg-[#e8c547]/10 border border-[#e8c547]/30 p-3 rounded-xl text-[11px] text-[#8b7534] space-y-2"
                              : "bg-[#d4a5a5]/10 border border-[#d4a5a5]/30 p-3 rounded-xl text-[11px] text-[#8c4848] space-y-2"
                            }>
                              <div className="flex items-start gap-1.5 font-bold flex-wrap">
                                <AlertTriangle className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'}`} />
                                <span>{isLowConfidenceWashed ? '疑似洗評' : '判定：灌水洗評'} ({review.audit.confidenceScore}% 信心度)</span>
                                {!isLowConfidenceWashed && (
                                  hasCoT ? (
                                    <span className="ml-1 bg-amber-100 text-amber-800 text-[9px] font-black px-1.5 py-0.5 rounded-md border border-amber-300">
                                      二階 AI 攔截
                                    </span>
                                  ) : (
                                    <span className="ml-1 bg-rose-100 text-rose-800 text-[9px] font-black px-1.5 py-0.5 rounded-md border border-rose-300">
                                      一階規則攔截
                                    </span>
                                  )
                                )}
                              </div>
                              <div className="font-semibold opacity-90 pl-5 leading-relaxed">
                                <b>原因：</b>{review.audit.reason}
                              </div>

                              {/* Accordion Reasoning Path */}
                              {hasCoT && (
                                <div className={`mt-2 pt-2 border-t ${isLowConfidenceWashed ? 'border-[#e8c547]/20' : 'border-[#d4a5a5]/20'}`}>
                                  <button
                                    onClick={() => toggleCoT(selectedInspectorTab, rIdx)}
                                    className={`flex items-center justify-between w-full text-left text-[10px] font-bold ${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'} bg-[#f5f1e8]/40 hover:bg-[#f5f1e8]/80 px-2.5 py-1.5 rounded-lg border border-[#d4c5b0]/30 transition-colors cursor-pointer`}
                                  >
                                    <span className="flex items-center gap-1.5">
                                      <span>AI 思考鏈 (CoT 推理)</span>
                                    </span>
                                    {cotExpanded ? (
                                      <ChevronUp className={`w-3.5 h-3.5 ${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'}`} />
                                    ) : (
                                      <ChevronDown className={`w-3.5 h-3.5 ${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'}`} />
                                    )}
                                  </button>

                                  <AnimatePresence initial={false}>
                                    {cotExpanded && (
                                      <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: 'auto', opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        transition={{ duration: 0.2 }}
                                        className="overflow-hidden"
                                      >
                                        <div className="mt-2 pl-2 text-[10px] space-y-2">
                                          <div className={`${isLowConfidenceWashed ? 'text-[#8b7534]/90' : 'text-[#8c4848]/90'} leading-relaxed bg-[#f5f1e8]/60 p-2.5 rounded-lg italic border border-[#d4c5b0]/30`}>
                                            <b>推理過程：</b>{review.audit.reasoningPath}
                                          </div>
                                          <div className="grid grid-cols-3 gap-2 text-[9px] text-center pt-1 font-bold">
                                            <div className={`${isLowConfidenceWashed ? 'bg-[#e8c547]/20' : 'bg-[#d4a5a5]/20'} py-1 px-1.5 rounded`}>
                                              利益誘因: <span className={`${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'} font-black`}>{review.audit.incentiveIntensity}/5</span>
                                            </div>
                                            <div className={`${isLowConfidenceWashed ? 'bg-[#e8c547]/20' : 'bg-[#d4a5a5]/20'} py-1 px-1.5 rounded`}>
                                              情感真實: <span className={`${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'} font-black`}>{review.audit.sentimentAuthenticity}/5</span>
                                            </div>
                                            <div className={`${isLowConfidenceWashed ? 'bg-[#e8c547]/20' : 'bg-[#d4a5a5]/20'} py-1 px-1.5 rounded`}>
                                              描述細緻: <span className={`${isLowConfidenceWashed ? 'text-[#8b7534]' : 'text-[#8c4848]'} font-black`}>{review.audit.descriptionGranularity}/5</span>
                                            </div>
                                          </div>
                                        </div>
                                      </motion.div>
                                    )}
                                  </AnimatePresence>
                                </div>
                              )}
                            </div>
                          ) : isLowInfo ? (
                            <div className="bg-gray-100 border border-gray-300 p-3 rounded-xl text-[11px] text-gray-600 space-y-2">
                              <div className="flex items-start gap-1.5 font-bold flex-wrap">
                                <HelpCircle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-gray-500" />
                                <span>低資訊評論 ({review.audit.confidenceScore}% 信心度)</span>
                              </div>
                              <div className="font-semibold opacity-90 pl-5 leading-relaxed">
                                <b>原因：</b>{review.audit.reason}
                              </div>
                            </div>
                          ) : (
                            <div className="bg-[#6b8e7f]/10 border border-[#6b8e7f]/30 p-3 rounded-xl text-[11px] text-[#304a3e] space-y-2">
                              <div className="flex items-start gap-1.5 font-bold flex-wrap">
                                <Check className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[#6b8e7f]" />
                                <span>判定：真實評論 ({review.audit.confidenceScore}% 信心度)</span>
                                {hasCoT && (
                                  <span className="ml-1 bg-emerald-100 text-emerald-800 text-[9px] font-black px-1.5 py-0.5 rounded-md border border-emerald-300">
                                    二階 AI 認證
                                  </span>
                                )}
                              </div>
                              <div className="font-semibold opacity-90 pl-5 leading-relaxed">
                                <b>原因：</b>{review.audit.reason}
                              </div>

                              {/* Accordion Reasoning Path */}
                              {hasCoT && (
                                <div className="mt-2 pt-2 border-t border-[#6b8e7f]/20">
                                  <button
                                    onClick={() => toggleCoT(selectedInspectorTab, rIdx)}
                                    className="flex items-center justify-between w-full text-left text-[10px] font-bold text-[#304a3e] bg-[#f5f1e8]/40 hover:bg-[#f5f1e8]/80 px-2.5 py-1.5 rounded-lg border border-[#d4c5b0]/30 transition-colors cursor-pointer"
                                  >
                                    <span className="flex items-center gap-1.5">
                                      <span>AI 思考鏈 (CoT 推理)</span>
                                    </span>
                                    {cotExpanded ? (
                                      <ChevronUp className="w-3.5 h-3.5 text-[#6b8e7f]" />
                                    ) : (
                                      <ChevronDown className="w-3.5 h-3.5 text-[#6b8e7f]" />
                                    )}
                                  </button>

                                  <AnimatePresence initial={false}>
                                    {cotExpanded && (
                                      <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: 'auto', opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        transition={{ duration: 0.2 }}
                                        className="overflow-hidden"
                                      >
                                        <div className="mt-2 pl-2 text-[10px] space-y-2">
                                          <div className="text-[#304a3e]/90 leading-relaxed bg-[#f5f1e8]/60 p-2.5 rounded-lg italic border border-[#d4c5b0]/30">
                                            <b>推理過程：</b>{review.audit.reasoningPath}
                                          </div>
                                          <div className="grid grid-cols-3 gap-2 text-[9px] text-center pt-1 font-bold">
                                            <div className="bg-[#6b8e7f]/20 py-1 px-1.5 rounded">
                                              利益誘因: <span className="text-[#304a3e] font-black">{review.audit.incentiveIntensity}/5</span>
                                            </div>
                                            <div className="bg-[#6b8e7f]/20 py-1 px-1.5 rounded">
                                              情感真實: <span className="text-[#304a3e] font-black">{review.audit.sentimentAuthenticity}/5</span>
                                            </div>
                                            <div className="bg-[#6b8e7f]/20 py-1 px-1.5 rounded">
                                              描述細緻: <span className="text-[#304a3e] font-black">{review.audit.descriptionGranularity}/5</span>
                                            </div>
                                          </div>
                                        </div>
                                      </motion.div>
                                    )}
                                  </AnimatePresence>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              );
            })()}
          </motion.div>
        )}

        {/* Action Buttons */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="mt-10 flex gap-5 justify-center flex-wrap"
        >
          <motion.button
            onClick={() => navigate('/analyzer')}
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-[#6b8e7f] hover:bg-[#5b7d6e] text-white px-8 py-3.5 rounded-full font-black shadow-[4px_4px_0px_0px_#4a5d52] hover:shadow-[6px_6px_0px_0px_#4a5d52] border-3 border-[#4a5d52] transition-all cursor-pointer text-sm md:text-base font-display tracking-wider active:translate-y-1 active:shadow-none"
          >
            重新對比分析店家
          </motion.button>
          <motion.button
            onClick={() => navigate('/')}
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-white hover:bg-[#f5f1e8] text-[#4a5d52] px-8 py-3.5 rounded-full font-black shadow-[4px_4px_0px_0px_#4a5d52] hover:shadow-[6px_6px_0px_0px_#4a5d52] border-3 border-[#4a5d52] transition-all cursor-pointer text-sm md:text-base font-display tracking-wider active:translate-y-1 active:shadow-none"
          >
            返回首頁
          </motion.button>
        </motion.div>
      </div>
    </div>
  );
}
