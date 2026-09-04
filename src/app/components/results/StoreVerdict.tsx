import { motion } from 'motion/react';
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
  const total = result.totalReviews;

  const incentiveCount = result.issues.timeAnomaly;
  const templateCount = result.issues.templateText;
  const discrepancyCount = result.issues.vague;
  const lowContentCount = result.issues.noText + result.issues.lowInfo;
  const cleanCount = total - result.suspiciousReviews - lowContentCount - result.issues.unaudited;

  const pct = (n: number) => total > 0 ? ((n / total) * 100).toFixed(1) : '0.0';

  const composition = [
    { label: '促銷型', sublabel: '打卡送餐', count: incentiveCount, color: 'bg-[var(--semantic-danger)]' },
    { label: '模板型', sublabel: '套版複製', count: templateCount, color: 'bg-[var(--semantic-warning)]' },
    { label: '語意矛盾', sublabel: '評分文字割裂', count: discrepancyCount, color: 'bg-ink-subtle' },
    { label: '低內容', sublabel: '純星等或過短', count: lowContentCount, color: 'bg-ink-tertiary' },
    { label: '自然評論', sublabel: '通過檢核', count: cleanCount, color: 'bg-[var(--semantic-success)]' },
  ];

  return (
    <div className="border-2 border-ink">
      {/* Header band */}
      <div className="bg-ink text-background px-5 py-2.5 flex items-center justify-between">
        <span className="text-sm font-semibold tracking-wide">評論檢驗報告</span>
        <span className="text-xs font-mono opacity-60 tracking-wider">REVIEW AUDIT REPORT</span>
      </div>

      <div className="px-5 py-5">
        {/* Store name */}
        <h2 className="text-2xl font-semibold text-ink tracking-tight mb-4">
          {storeName}
        </h2>

        {/* Rating comparison */}
        <div className="flex items-baseline gap-3 flex-wrap mb-3">
          <span className="text-sm text-ink-subtle">原始</span>
          <span className="text-xl font-semibold text-ink-muted line-through font-mono tabular-nums">
            {result.originalRating.toFixed(2)}★
          </span>
          <span className="text-ink-tertiary">→</span>
          <span className="text-sm text-ink-subtle">校正</span>
          <span className="text-2xl font-bold text-ink font-mono tabular-nums">
            {result.filteredRating.toFixed(2)}★
          </span>
          {drop > 0 && (
            <span className="text-sm font-medium text-[var(--semantic-danger)] font-mono tabular-nums">
              ▼{drop.toFixed(2)}
            </span>
          )}
        </div>
        {result.reviewAvgRating != null && Math.abs(result.originalRating - result.reviewAvgRating) >= 0.05 && (
          <p className="text-xs text-ink-tertiary mb-5">
            最近 {total} 則平均 {result.reviewAvgRating.toFixed(2)}★
            {result.googleReviewsCount != null && (
              <span>（Google 全部 {result.googleReviewsCount.toLocaleString()} 則為 {result.originalRating.toFixed(1)}★）</span>
            )}
          </p>
        )}

        <hr className="border-hairline-strong mb-5" />

        {/* Trust score */}
        <div className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-ink">結構健康度</span>
            <span className={`text-lg font-bold font-mono tabular-nums ${getHealthTextColor(result.trustScore)}`}>
              {result.trustScore}
              <span className="text-ink-tertiary text-sm font-normal"> / 100</span>
            </span>
          </div>
          <div className="w-full h-2 bg-surface-3 overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${result.trustScore}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
              className={`h-full ${getHealthColor(result.trustScore)}`}
            />
          </div>
        </div>

        <hr className="border-hairline-strong mb-5" />

        {/* Composition — nutrition label style */}
        <div className="mb-5">
          <div className="flex items-baseline justify-between mb-4">
            <h3 className="text-sm font-semibold text-ink tracking-tight">評論成分</h3>
            <span className="text-[11px] text-ink-tertiary font-mono tracking-wider">COMPOSITION</span>
          </div>
          <div className="space-y-3">
            {composition.map(item => (
              <div key={item.label}>
                <div className="flex items-baseline justify-between mb-1">
                  <span className="text-sm text-ink">
                    {item.label}
                    <span className="text-ink-tertiary text-xs ml-1.5">({item.sublabel})</span>
                  </span>
                  <span className="text-sm font-mono tabular-nums text-ink">
                    {item.count} 則
                    <span className="text-ink-subtle ml-2">{pct(item.count)}%</span>
                  </span>
                </div>
                <div className="w-full h-1.5 bg-surface-3 overflow-hidden">
                  <div
                    className={`h-full transition-all ${item.color}`}
                    style={{ width: `${total > 0 ? (item.count / total) * 100 : 0}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <hr className="border-hairline-strong mb-4" />

        {/* Verdict */}
        <p className="text-sm text-ink-muted leading-relaxed">
          偵測到 <span className="font-mono tabular-nums font-medium text-ink">{result.suspiciousReviews}</span> 則結構標記評論，佔總數 <span className="font-mono tabular-nums font-medium text-ink">{total > 0 ? ((result.suspiciousReviews / total) * 100).toFixed(1) : 0}%</span>。{getVerdictText(result.trustScore)}
        </p>
      </div>
    </div>
  );
}
