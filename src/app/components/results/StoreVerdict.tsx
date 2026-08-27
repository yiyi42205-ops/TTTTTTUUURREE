import { motion } from 'motion/react';
import { Shield, ArrowRight, TrendingDown } from 'lucide-react';
import type { ShopStats } from '../../utils/auditEngine';

interface StoreVerdictProps {
  result: ShopStats;
  storeName: string;
}

function getVerdictText(trustScore: number): string {
  if (trustScore >= 90) return '評論結構高度自然，未發現明顯異常模式。';
  if (trustScore >= 75) return '整體結構健康，僅有少量可疑特徵。';
  if (trustScore >= 60) return '部分評論呈現結構異常，建議留意參考。';
  if (trustScore >= 40) return '多數評論具有結構特徵，評分可信度偏低。';
  return '大量評論呈現高度結構化特徵，評分嚴重偏離自然分佈。';
}

function getHealthColor(trustScore: number): string {
  if (trustScore >= 75) return 'bg-[var(--semantic-success)]';
  if (trustScore >= 50) return 'bg-[var(--semantic-warning)]';
  return 'bg-[var(--semantic-danger)]';
}

function getHealthTextColor(trustScore: number): string {
  if (trustScore >= 75) return 'text-[var(--semantic-success)]';
  if (trustScore >= 50) return 'text-[var(--semantic-warning)]';
  return 'text-[var(--semantic-danger)]';
}

export function StoreVerdict({ result, storeName }: StoreVerdictProps) {
  const drop = result.originalRating - result.filteredRating;
  const hasMajorDrop = drop >= 0.3 || result.trustScore < 80;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="bg-surface-1 border border-hairline rounded-xl p-5 md:p-6"
    >
      {/* Store name */}
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl md:text-2xl font-semibold text-ink tracking-[-0.6px]">
          {storeName}
        </h2>
        {hasMajorDrop && (
          <span className="flex items-center gap-1 bg-[var(--semantic-danger)]/10 text-[var(--semantic-danger)] border border-[var(--semantic-danger)]/20 px-2.5 py-1 rounded-lg text-xs font-medium">
            <TrendingDown className="w-3.5 h-3.5" />
            評分落差大
          </span>
        )}
      </div>

      {/* Big rating comparison */}
      <div className="flex items-center justify-center gap-3 md:gap-5 py-4 mb-5 bg-surface-2 rounded-xl border border-hairline">
        <div className="text-center" title="Google Maps 上的公開評分（含所有評論，未過濾）">
          <span className="block text-xs text-ink-subtle font-medium mb-1">原始評分</span>
          <span className="text-2xl md:text-3xl font-semibold text-ink-muted tracking-[-1px] line-through decoration-ink-subtle/40">
            {result.originalRating.toFixed(2)}
          </span>
          <span className="text-ink-subtle ml-0.5">★</span>
        </div>

        <ArrowRight className="w-5 h-5 text-ink-tertiary shrink-0" />

        <div className="text-center">
          <span className="block text-xs text-[var(--semantic-danger)] font-medium mb-1">扣減</span>
          <span className="text-lg md:text-xl font-semibold text-[var(--semantic-danger)] tracking-[-0.6px]">
            -{drop.toFixed(2)}★
          </span>
        </div>

        <ArrowRight className="w-5 h-5 text-ink-tertiary shrink-0" />

        <div className="text-center" title="移除結構異常評論後，以信任權重重新計算的真實評分。落差越大代表水分越多。">
          <span className="block text-xs text-primary font-medium mb-1">校正後</span>
          <span className="text-2xl md:text-3xl font-semibold text-primary tracking-[-1px]">
            {result.filteredRating.toFixed(2)}
          </span>
          <span className="text-primary/60 ml-0.5">★</span>
        </div>
      </div>

      {/* Structural health score */}
      <div className="space-y-2.5">
        <div className="flex items-center justify-between">
          <span
            className="flex items-center gap-1.5 text-sm text-ink-muted font-medium cursor-help"
            title="0–100 分，評估評論整體自然程度。越高代表評論越真實，洗評可能性越低。"
          >
            <Shield className="w-4 h-4 text-ink-subtle" />
            結構健康度
          </span>
          <span className={`text-lg font-semibold tracking-[-0.4px] ${getHealthTextColor(result.trustScore)}`}>
            {result.trustScore}<span className="text-ink-subtle text-sm font-normal">/100</span>
          </span>
        </div>

        {/* Progress bar */}
        <div className="w-full h-2 bg-surface-3 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${result.trustScore}%` }}
            transition={{ duration: 0.8, ease: 'easeOut', delay: 0.2 }}
            className={`h-full rounded-full ${getHealthColor(result.trustScore)}`}
          />
        </div>

        {/* Verdict text */}
        <p className="text-sm text-ink-subtle leading-relaxed">
          {getVerdictText(result.trustScore)}
          <span className="text-ink-tertiary ml-1">
            (偵測到 {result.suspiciousReviews} 則結構標記評論，佔總數 {result.totalReviews > 0 ? ((result.suspiciousReviews / result.totalReviews) * 100).toFixed(0) : 0}%)
          </span>
        </p>
      </div>
    </motion.div>
  );
}
