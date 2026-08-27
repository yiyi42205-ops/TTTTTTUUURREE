import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { X, ChevronRight, ArrowRight, Shield, ListFilter } from 'lucide-react';

interface ResultsGuideProps {
  onDismiss: () => void;
}

interface GuideStep {
  id: number;
  title: string;
  description: string;
  anchor: 'rating' | 'trust' | 'inspector';
  icon: React.ReactNode;
  position: 'top' | 'bottom';
}

const guideSteps: GuideStep[] = [
  {
    id: 0,
    anchor: 'rating',
    title: '⭐ 星等對比',
    description: '左側是 Google 原始評分（含所有評論），右側是移除結構異常評論後的校正評分。兩者落差越大，代表這間店的評論水分越多。',
    icon: <ArrowRight className="w-4 h-4" />,
    position: 'bottom',
  },
  {
    id: 1,
    anchor: 'trust',
    title: '🛡 結構健康度',
    description: '0–100 分，評估評論的整體自然程度。75 分以上相對健康；低於 50 分建議謹慎參考 Google 評分。',
    icon: <Shield className="w-4 h-4" />,
    position: 'bottom',
  },
  {
    id: 2,
    anchor: 'inspector',
    title: '🔍 完整結構分析',
    description: '點擊可展開查看所有評論的逐則判定結果，包含每則評論被標記的原因和 AI 推理依據。',
    icon: <ListFilter className="w-4 h-4" />,
    position: 'top',
  },
];

export function ResultsGuide({ onDismiss }: ResultsGuideProps) {
  const [step, setStep] = useState(0);

  const current = guideSteps[step];
  const isLast = step === guideSteps.length - 1;

  const goNext = () => {
    if (isLast) {
      onDismiss();
    } else {
      setStep((s) => s + 1);
    }
  };

  // Map anchor to data-attr for highlight — rendered as a floating tooltip panel
  // instead of true DOM highlight (avoids z-index complexity with dynamic content)
  const anchorLabels: Record<GuideStep['anchor'], string> = {
    rating: '星等對比區',
    trust: '結構健康度區',
    inspector: '完整結構分析',
  };

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={current.id}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.22 }}
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[9990] w-full max-w-sm px-4"
      >
        <div className="bg-surface-1 border border-primary/30 rounded-2xl shadow-2xl overflow-hidden">
          {/* Indicator strip */}
          <div className="flex h-0.5">
            {guideSteps.map((s) => (
              <div
                key={s.id}
                className={`flex-1 transition-colors duration-300 ${
                  s.id <= step ? 'bg-primary' : 'bg-surface-3'
                }`}
              />
            ))}
          </div>

          <div className="p-4">
            {/* Header */}
            <div className="flex items-start justify-between gap-3 mb-2">
              <div>
                <div className="text-[11px] text-primary font-semibold uppercase tracking-wider mb-1">
                  結果頁快速導讀 {step + 1}/{guideSteps.length}
                </div>
                <h4 className="text-sm font-semibold text-ink tracking-[-0.2px]">
                  {current.title}
                </h4>
              </div>
              <button
                onClick={onDismiss}
                className="text-ink-tertiary hover:text-ink-subtle transition-colors cursor-pointer p-1 rounded-lg hover:bg-surface-2 shrink-0"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Anchor hint */}
            <div className="inline-flex items-center gap-1 text-[11px] text-primary bg-primary/10 border border-primary/20 rounded-md px-2 py-0.5 mb-2.5">
              {current.icon}
              <span>查看：{anchorLabels[current.anchor]}</span>
            </div>

            {/* Description */}
            <p className="text-xs text-ink-subtle leading-relaxed mb-3">
              {current.description}
            </p>

            {/* Actions */}
            <div className="flex items-center justify-between">
              <button
                onClick={onDismiss}
                className="text-[11px] text-ink-tertiary hover:text-ink-subtle transition-colors cursor-pointer underline underline-offset-2"
              >
                跳過引導
              </button>
              <motion.button
                onClick={goNext}
                whileTap={{ scale: 0.97 }}
                className="flex items-center gap-1.5 bg-primary hover:bg-primary-hover text-white text-xs font-medium px-3.5 py-1.5 rounded-lg transition-colors cursor-pointer"
              >
                {isLast ? (
                  '開始探索'
                ) : (
                  <>
                    下一個提示
                    <ChevronRight className="w-3.5 h-3.5" />
                  </>
                )}
              </motion.button>
            </div>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
