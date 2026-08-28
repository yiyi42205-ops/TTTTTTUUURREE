import { motion } from 'motion/react';
import { Loader2, Check, Database, Shield } from 'lucide-react';
import type { ShopStats } from '../../utils/auditEngine';

interface LoadingStateProps {
  shopResults: ShopStats[];
  showLoader: boolean;
  cleanStoreName: (name: string) => string;
}

export function LoadingState({ shopResults, showLoader, cleanStoreName }: LoadingStateProps) {
  // Initial loading - no data yet
  if (!showLoader || shopResults.length === 0) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="bg-surface-1 border border-hairline rounded-xl p-8 text-center max-w-sm"
        >
          <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-4" />
          <p className="text-sm text-ink-muted font-medium">
            正在讀取評價數據集庫，請稍候...
          </p>
        </motion.div>
      </div>
    );
  }

  // Stage 2 in progress - show checklist + Stage 1 preview
  return (
    <div className="max-w-5xl mx-auto w-full grid grid-cols-1 lg:grid-cols-12 gap-6 items-start px-4 py-8">
      {/* Left: Progress checklist */}
      <div className="lg:col-span-5">
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-surface-1 border border-hairline rounded-xl p-6 relative overflow-hidden"
        >
          {/* Scan line */}
          <div className="absolute left-0 right-0 h-px bg-ink/10 top-0" />

          <Loader2 className="w-8 h-8 animate-spin text-primary mb-4" />
          <h3 className="text-base font-semibold text-ink tracking-[-0.4px] mb-1.5">
            雙階段 AI 混合審計進行中
          </h3>
          <p className="text-xs text-ink-subtle mb-5 leading-relaxed">
            系統正執行啟發式規則篩選、AI 語意矛盾檢索、大模型思維鏈推理。
          </p>

          <div className="space-y-2.5 bg-surface-2 p-4 rounded-lg border border-hairline">
            <div className="flex items-center gap-2.5 text-xs text-ink-muted">
              <Check className="w-3.5 h-3.5 text-[var(--semantic-success)]" />
              <span>階段一：本地正則規則匹配</span>
            </div>
            <div className="flex items-center gap-2.5 text-xs text-ink-muted">
              <Check className="w-3.5 h-3.5 text-[var(--semantic-success)]" />
              <span>階段一：時間發布異常密度計算</span>
            </div>
            <div className="flex items-center gap-2.5 text-xs text-primary">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-primary" />
              </span>
              <span>階段二：調用大語言模型語意複審中...</span>
            </div>
          </div>
        </motion.div>
      </div>

      {/* Right: Stage 1 report preview */}
      <div className="lg:col-span-7">
        <div className="bg-surface-1 border border-hairline rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-medium text-ink border-b border-hairline pb-3 flex items-center gap-2 tracking-[-0.2px]">
            <Database className="w-4 h-4 text-ink-subtle" />
            第一階段：啟發式規則分析報告 (已完成)
          </h3>
          <div className="space-y-3">
            {shopResults.map((shop, idx) => {
              const reviews = shop.auditedReviews || [];
              const stage1Washed = reviews.filter(r => r.audit.issueType !== null);
              const stage1Count = stage1Washed.length;
              const ambiguousReviews = reviews.filter(r => r.stars === 5 && r.audit.issueType === null);
              const stage2Sent = ambiguousReviews.length;

              const remainingReviews = reviews.filter(r => r.audit.issueType === null);
              const heuristicRating = remainingReviews.length > 0
                ? Number((remainingReviews.reduce((sum, r) => sum + r.stars, 0) / remainingReviews.length).toFixed(2))
                : shop.originalRating;

              return (
                <div key={idx} className="bg-surface-2 p-4 rounded-lg border border-hairline space-y-3">
                  <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-2">
                    <div>
                      <h4 className="font-medium text-ink text-sm flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-sm bg-primary" />
                        {cleanStoreName(shop.storeName)}
                      </h4>
                      <p className="text-[11px] text-ink-subtle mt-0.5">
                        {shop.googleReviewsCount
                          ? `Google 評論：${shop.googleReviewsCount} 則（已抽樣 ${shop.totalReviews} 則）`
                          : `總評論數量：${shop.totalReviews} 則`}
                      </p>
                    </div>
                    <div className="flex items-center gap-3 bg-surface-3 px-3 py-1.5 rounded-lg border border-hairline self-start sm:self-auto">
                      <div className="text-right">
                        <div className="text-[10px] text-ink-subtle">原始評分</div>
                        <div className="text-xs font-medium text-ink-muted line-through">{shop.originalRating.toFixed(1)} ★</div>
                      </div>
                      <div className="h-5 w-px bg-hairline" />
                      <div className="text-right">
                        <div className="text-[10px] text-ink-subtle">一階校正後</div>
                        <div className="text-sm font-semibold text-primary">{heuristicRating.toFixed(2)} ★</div>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-hairline text-center">
                    <div className="bg-surface-3 p-2 rounded-lg border border-hairline">
                      <div className="text-[10px] text-ink-subtle">一階結構標記</div>
                      <div className="text-xs font-semibold text-[var(--semantic-danger)] mt-0.5">{stage1Count} 則</div>
                    </div>
                    <div className="bg-surface-3 p-2 rounded-lg border border-hairline">
                      <div className="text-[10px] text-ink-subtle">二階 AI 待審</div>
                      <div className="text-xs font-semibold text-[var(--semantic-warning)] mt-0.5">{stage2Sent} 則</div>
                    </div>
                    <div className="bg-surface-3 p-2 rounded-lg border border-hairline flex flex-col justify-center items-center">
                      <div className="text-[10px] text-ink-subtle">當前進度</div>
                      <div className="text-[10px] font-medium text-primary mt-0.5 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
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
    </div>
  );
}
