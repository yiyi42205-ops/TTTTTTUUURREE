import React from 'react';
import { AlertTriangle, Sparkles, ExternalLink, ShieldCheck } from 'lucide-react';
import { motion } from 'motion/react';

export interface SummaryWarning {
  summary: string;
  sourceReviewIds: string[];
}

export interface SummaryRecommendation {
  item: string;
  reason: string;
  sourceReviewIds: string[];
}

export interface SummaryData {
  warnings: SummaryWarning[];
  recommendations: SummaryRecommendation[];
}

interface SummaryBannerProps {
  summary: SummaryData;
  onSourceClick: (reviewId: string) => void;
}

export function SummaryBanner({ summary, onSourceClick }: SummaryBannerProps) {
  const hasWarnings = summary.warnings && summary.warnings.length > 0;
  const hasRecommendations = summary.recommendations && summary.recommendations.length > 0;

  if (!hasWarnings && !hasRecommendations) {
    return null;
  }

  return (
    <motion.div 
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-6"
    >
      <div className="bg-gray-800/50 px-4 py-3 border-b border-gray-800 flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-blue-400" />
        <h3 className="font-semibold text-gray-100">AI 單店總結</h3>
      </div>
      
      <div className="p-4 flex flex-col gap-4">
        {hasWarnings && (
          <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-5 h-5 text-orange-400" />
              <h4 className="font-medium text-orange-400">避雷提示</h4>
            </div>
            <ul className="space-y-3">
              {summary.warnings.map((warning, idx) => (
                <li key={idx} className="text-gray-300 text-sm flex flex-col sm:flex-row sm:items-start gap-2">
                  <span className="flex-1">{warning.summary}</span>
                  <div className="flex flex-wrap gap-1 shrink-0 mt-1 sm:mt-0">
                    {warning.sourceReviewIds.map((id, i) => (
                      <button
                        key={i}
                        onClick={() => onSourceClick(id)}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-orange-500/20 text-orange-300 hover:bg-orange-500/30 transition-colors text-xs"
                      >
                        來源 <ExternalLink className="w-3 h-3" />
                      </button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {hasRecommendations && (
          <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck className="w-5 h-5 text-emerald-400" />
              <h4 className="font-medium text-emerald-400">推薦品項</h4>
            </div>
            <ul className="space-y-3">
              {summary.recommendations.map((rec, idx) => (
                <li key={idx} className="text-gray-300 text-sm flex flex-col sm:flex-row sm:items-start gap-2">
                  <div className="flex-1">
                    <span className="font-semibold text-emerald-300 mr-2">{rec.item}</span>
                    <span>{rec.reason}</span>
                  </div>
                  <div className="flex flex-wrap gap-1 shrink-0 mt-1 sm:mt-0">
                    {rec.sourceReviewIds.map((id, i) => (
                      <button
                        key={i}
                        onClick={() => onSourceClick(id)}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 transition-colors text-xs"
                      >
                        來源 <ExternalLink className="w-3 h-3" />
                      </button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </motion.div>
  );
}
