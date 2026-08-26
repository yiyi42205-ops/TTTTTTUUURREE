import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ChevronDown, ChevronUp, Star, Shield, Check,
  AlertTriangle, HelpCircle, Search, ListFilter,
} from 'lucide-react';
import type { ShopStats, AuditResult } from '../../utils/auditEngine';
import type { Review } from '../../utils/csvParser';

interface ReviewInspectorProps {
  result: ShopStats;
  storeIndex: number;
  inspectSearch: string;
  inspectFilter: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean';
  onSearchChange: (value: string) => void;
  onFilterChange: (value: 'all' | 'washed' | 'stage1' | 'stage2' | 'clean') => void;
  expandedCoT: { [key: string]: boolean };
  onToggleCoT: (storeIndex: number, reviewIndex: number) => void;
}

export function ReviewInspector({
  result,
  storeIndex,
  inspectSearch,
  inspectFilter,
  onSearchChange,
  onFilterChange,
  expandedCoT,
  onToggleCoT,
}: ReviewInspectorProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const stage1Count = result.auditedReviews.filter(r => r.audit.isWashed && !r.audit.reasoningPath).length;
  const stage2Count = result.auditedReviews.filter(r => r.audit.isWashed && Boolean(r.audit.reasoningPath)).length;

  const filteredReviews = result.auditedReviews.filter(r => {
    const matchesSearch =
      inspectSearch === '' ||
      (r.text || '').toLowerCase().includes(inspectSearch.toLowerCase()) ||
      r.username.toLowerCase().includes(inspectSearch.toLowerCase());

    if (!matchesSearch) return false;

    if (inspectFilter === 'all') return true;
    if (inspectFilter === 'washed') return r.audit.isWashed;
    if (inspectFilter === 'clean') return !r.audit.isWashed;
    if (inspectFilter === 'stage1') return r.audit.isWashed && !r.audit.reasoningPath;
    if (inspectFilter === 'stage2') return r.audit.isWashed && Boolean(r.audit.reasoningPath);
    return true;
  });

  const filterTabs: { id: typeof inspectFilter; label: string }[] = [
    { id: 'all', label: `全部 (${result.auditedReviews.length})` },
    { id: 'washed', label: `結構標記 (${result.suspiciousReviews})` },
    { id: 'stage1', label: `Stage 1 (${stage1Count})` },
    { id: 'stage2', label: `Stage 2 (${stage2Count})` },
    { id: 'clean', label: `自然評論 (${result.totalReviews - result.suspiciousReviews})` },
  ];

  return (
    <div className="bg-surface-1 border border-hairline rounded-xl overflow-hidden">
      {/* Collapsed toggle button */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-5 py-4 text-sm font-medium text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-2">
          <ListFilter className="w-4 h-4 text-ink-subtle" />
          展開完整結構分析
          <span className="text-xs text-ink-tertiary font-normal">
            ({result.totalReviews} 則評論)
          </span>
        </span>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-ink-subtle" />
        ) : (
          <ChevronDown className="w-4 h-4 text-ink-subtle" />
        )}
      </button>

      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            {/* Search + filters */}
            <div className="px-5 pb-4 space-y-3 border-t border-hairline pt-4">
              {/* Search input */}
              <div className="relative">
                <Search className="w-4 h-4 text-ink-tertiary absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={inspectSearch}
                  onChange={(e) => onSearchChange(e.target.value)}
                  placeholder="搜尋評論關鍵字或用戶名..."
                  className="w-full pl-9 pr-3 py-2 bg-surface-2 border border-hairline rounded-lg text-sm text-ink placeholder-ink-tertiary focus:outline-none focus:border-primary/50 font-sans"
                />
              </div>

              {/* Filter tabs */}
              <div className="flex flex-wrap gap-1.5">
                {filterTabs.map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => onFilterChange(tab.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                      inspectFilter === tab.id
                        ? 'bg-primary text-white'
                        : 'bg-surface-2 text-ink-subtle border border-hairline hover:text-ink-muted hover:border-hairline-strong'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Review list */}
            <div className="max-h-[500px] overflow-y-auto border-t border-hairline">
              {filteredReviews.length === 0 ? (
                <div className="text-center py-12 text-sm text-ink-subtle">
                  無符合篩選條件的評價內容。
                </div>
              ) : (
                <div className="divide-y divide-hairline">
                  {filteredReviews.map((review, rIdx) => (
                    <ReviewCard
                      key={rIdx}
                      review={review}
                      storeIndex={storeIndex}
                      reviewIndex={rIdx}
                      isCoTExpanded={!!expandedCoT[`${storeIndex}-${rIdx}`]}
                      onToggleCoT={onToggleCoT}
                    />
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ---- Individual Review Card ---- */

interface ReviewCardProps {
  review: Review & { audit: AuditResult };
  storeIndex: number;
  reviewIndex: number;
  isCoTExpanded: boolean;
  onToggleCoT: (storeIndex: number, reviewIndex: number) => void;
}

function ReviewCard({ review, storeIndex, reviewIndex, isCoTExpanded, onToggleCoT }: ReviewCardProps) {
  const { audit } = review;
  const isWashed = audit.isWashed;
  const isLowInfo = audit.issueType === 'low_info';
  const isLowConfidenceWashed = isWashed && audit.confidenceScore < 50;
  const hasCoT = !!audit.reasoningPath;

  const starArr = Array.from({ length: review.stars });

  // Verdict badge
  let badgeBg: string;
  let badgeText: string;
  let badgeLabel: string;

  if (isWashed) {
    if (isLowConfidenceWashed) {
      badgeBg = 'bg-[var(--semantic-warning)]/10 border-[var(--semantic-warning)]/20 text-[var(--semantic-warning)]';
      badgeLabel = '疑似標記';
    } else {
      badgeBg = 'bg-[var(--semantic-danger)]/10 border-[var(--semantic-danger)]/20 text-[var(--semantic-danger)]';
      badgeLabel = '標記：符合結構特徵';
    }
  } else if (isLowInfo) {
    badgeBg = 'bg-surface-3 border-hairline text-ink-subtle';
    badgeLabel = '低資訊';
  } else {
    badgeBg = 'bg-[var(--semantic-success)]/10 border-[var(--semantic-success)]/20 text-[var(--semantic-success)]';
    badgeLabel = '自然評論';
  }

  // Audit box colors
  let auditBoxClass: string;
  if (isWashed) {
    auditBoxClass = isLowConfidenceWashed
      ? 'bg-[var(--semantic-warning)]/5 border-[var(--semantic-warning)]/15 text-[var(--semantic-warning)]'
      : 'bg-[var(--semantic-danger)]/5 border-[var(--semantic-danger)]/15 text-[var(--semantic-danger)]';
  } else if (isLowInfo) {
    auditBoxClass = 'bg-surface-3 border-hairline text-ink-subtle';
  } else {
    auditBoxClass = 'bg-[var(--semantic-success)]/5 border-[var(--semantic-success)]/15 text-[var(--semantic-success)]';
  }

  const verdictIcon = isWashed
    ? <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
    : isLowInfo
    ? <HelpCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
    : <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />;

  const verdictLabel = isWashed
    ? (isLowConfidenceWashed ? '疑似結構異常' : '標記：符合結構特徵')
    : isLowInfo
    ? '低資訊評論'
    : '自然評論';

  return (
    <div className="px-5 py-3.5 hover:bg-surface-2/50 transition-colors">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-sm text-ink truncate">{review.username}</span>
          <div className="flex gap-0.5 shrink-0">
            {starArr.map((_, i) => (
              <Star key={i} className="w-3 h-3 fill-[var(--semantic-warning)] stroke-[var(--semantic-warning)]" />
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {review.time && (
            <span className="text-[11px] text-ink-tertiary">{review.time}</span>
          )}
          <span className={`px-2 py-0.5 rounded text-[10px] font-medium border ${badgeBg}`}>
            {badgeLabel}
          </span>
        </div>
      </div>

      {/* Review text */}
      <p className="text-sm text-ink-muted leading-relaxed mb-2.5">
        {review.text || <span className="text-ink-tertiary italic">（此評論無內文）</span>}
      </p>

      {/* Audit verdict box */}
      <div className={`p-3 rounded-lg border text-xs leading-relaxed ${auditBoxClass}`}>
        <div className="flex items-start gap-1.5 font-medium flex-wrap mb-1">
          {verdictIcon}
          <span>{verdictLabel} ({audit.confidenceScore}% 信心度)</span>
          {isWashed && !isLowConfidenceWashed && (
            hasCoT ? (
              <span className="ml-1 bg-[var(--semantic-warning)]/15 text-[var(--semantic-warning)] text-[10px] font-medium px-1.5 py-0.5 rounded border border-[var(--semantic-warning)]/20">
                Stage 2 AI
              </span>
            ) : (
              <span className="ml-1 bg-[var(--semantic-danger)]/15 text-[var(--semantic-danger)] text-[10px] font-medium px-1.5 py-0.5 rounded border border-[var(--semantic-danger)]/20">
                Stage 1 規則
              </span>
            )
          )}
        </div>
        <div className="opacity-90 pl-5">
          <b>原因：</b>{audit.reason}
        </div>

        {/* CoT reasoning accordion */}
        {hasCoT && (
          <div className="mt-2 pt-2 border-t border-current/10">
            <button
              onClick={() => onToggleCoT(storeIndex, reviewIndex)}
              className="flex items-center justify-between w-full text-left text-[11px] font-medium bg-surface-2 hover:bg-surface-3 px-2.5 py-1.5 rounded-lg border border-hairline transition-colors cursor-pointer text-ink-muted"
            >
              <span>AI 推理鏈 (CoT)</span>
              {isCoTExpanded ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>

            <AnimatePresence initial={false}>
              {isCoTExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="mt-2 space-y-2">
                    <div className="text-[11px] text-ink-subtle leading-relaxed bg-surface-2 p-2.5 rounded-lg border border-hairline font-mono whitespace-pre-wrap">
                      {audit.reasoningPath}
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[10px] text-center font-medium">
                      <div className="bg-surface-2 border border-hairline py-1.5 px-1 rounded-lg">
                        <span className="text-ink-subtle">利益誘因</span>
                        <span className="block text-ink font-semibold">{audit.incentiveIntensity}/5</span>
                      </div>
                      <div className="bg-surface-2 border border-hairline py-1.5 px-1 rounded-lg">
                        <span className="text-ink-subtle">情感自然度</span>
                        <span className="block text-ink font-semibold">{audit.sentimentAuthenticity}/5</span>
                      </div>
                      <div className="bg-surface-2 border border-hairline py-1.5 px-1 rounded-lg">
                        <span className="text-ink-subtle">描述細緻</span>
                        <span className="block text-ink font-semibold">{audit.descriptionGranularity}/5</span>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}
