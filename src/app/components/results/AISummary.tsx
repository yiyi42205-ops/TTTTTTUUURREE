import { motion } from 'motion/react';
import { Sparkles, AlertTriangle, ThumbsUp, ThumbsDown } from 'lucide-react';

interface AISummaryProps {
  isLoading: boolean;
  summary: {
    answer: string;
    sufficient: boolean;
  } | null;
  storeName: string;
}

function SummarySkeleton() {
  return (
    <div className="space-y-2.5 animate-pulse">
      <div className="h-3.5 bg-surface-3 rounded-md w-full" />
      <div className="h-3.5 bg-surface-3 rounded-md w-[90%]" />
      <div className="h-3.5 bg-surface-3 rounded-md w-[75%]" />
    </div>
  );
}

export function AISummary({ isLoading, summary, storeName }: AISummaryProps) {
  if (!isLoading && !summary) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      className="bg-primary/5 border border-primary/20 rounded-xl p-5"
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center shrink-0">
          <Sparkles className="w-3.5 h-3.5 text-primary" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ink tracking-[-0.2px]">AI 智慧總結</h3>
          {!isLoading && (
            <p className="text-[11px] text-ink-tertiary">基於自然評論分析 · {storeName}</p>
          )}
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <SummarySkeleton />
      ) : summary ? (
        <div className="space-y-3">
          {/* Parse the answer to separate recommendation and avoid sections */}
          <div className="text-sm text-ink-muted leading-relaxed whitespace-pre-wrap">
            {summary.answer}
          </div>

          {!summary.sufficient && (
            <div className="flex items-center gap-1.5 bg-[var(--semantic-warning)]/10 border border-[var(--semantic-warning)]/20 text-[var(--semantic-warning)] text-xs px-3 py-2 rounded-lg">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span>評論資料有限，此總結僅供參考</span>
            </div>
          )}

          <div className="flex items-center gap-3 pt-1 border-t border-primary/10">
            <span className="text-[11px] text-ink-tertiary flex items-center gap-1">
              <ThumbsUp className="w-3 h-3" />
              推薦：評論中的亮點
            </span>
            <span className="text-[11px] text-ink-tertiary flex items-center gap-1">
              <ThumbsDown className="w-3 h-3" />
              避雷：需注意的面向
            </span>
          </div>
        </div>
      ) : null}
    </motion.div>
  );
}
