import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  X, ChevronRight, ChevronLeft, Shield, Globe, Layers, BarChart2, HelpCircle,
  Gift, Copy, MessageSquareWarning, Check, Star,
} from 'lucide-react';

interface OnboardingModalProps {
  onDismiss: () => void;
}

interface Step {
  id: number;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  content: React.ReactNode;
}

const steps: Step[] = [
  {
    id: 0,
    icon: <Shield className="w-8 h-8 text-primary" />,
    title: '歡迎使用疑騙真星',
    subtitle: 'TrueRating — 還原 Google 地圖上的真實評分',
    content: (
      <div className="space-y-3 text-sm text-ink-subtle leading-relaxed">
        <p>
          許多台灣餐廳店家透過「打卡送小菜」「五星好評換飲料」等促銷活動，
          大量累積<span className="text-ink font-medium">結構異常的五星評論</span>，
          導致 Google 地圖評分虛高。
        </p>
        <div className="bg-surface-2 border border-hairline rounded-xl p-4 space-y-2">
          <div className="flex items-start gap-2.5">
            <div className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-0.5">
              <Check className="w-3 h-3 text-primary" />
            </div>
            <span>偵測促銷型、模板型、語意矛盾等結構異常評論</span>
          </div>
          <div className="flex items-start gap-2.5">
            <div className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-0.5">
              <Check className="w-3 h-3 text-primary" />
            </div>
            <span>整合 Gemini AI 語意審查，精準識別非自發性評論</span>
          </div>
          <div className="flex items-start gap-2.5">
            <div className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-0.5">
              <Check className="w-3 h-3 text-primary" />
            </div>
            <span>輸出校正後的「真實評分」，幫助你做出正確的消費決策</span>
          </div>
        </div>
        <p className="text-xs text-ink-tertiary">
          本教學大約需要 1 分鐘，你可以隨時跳過。
        </p>
      </div>
    ),
  },
  {
    id: 1,
    icon: <Globe className="w-8 h-8 text-primary" />,
    title: '如何輸入店家？',
    subtitle: '支援 Google Maps 連結或直接輸入店名',
    content: (
      <div className="space-y-3">
        <div className="space-y-2.5">
          {/* Method 1 */}
          <div className="bg-surface-2 border border-hairline rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold bg-primary/20 text-primary px-2 py-0.5 rounded-md">方式一</span>
              <span className="text-sm font-medium text-ink">貼上 Google Maps 連結</span>
            </div>
            <p className="text-xs text-ink-subtle leading-relaxed mb-2">
              在 Google Maps 找到店家後，複製頁面網址（支援短連結和完整連結）：
            </p>
            <div className="bg-surface-3 rounded-lg px-3 py-2 font-mono text-[11px] text-ink-tertiary truncate">
              https://maps.app.goo.gl/xyz...
            </div>
            <div className="bg-surface-3 rounded-lg px-3 py-2 font-mono text-[11px] text-ink-tertiary truncate mt-1">
              https://www.google.com/maps/place/...
            </div>
          </div>

          {/* Method 2 */}
          <div className="bg-surface-2 border border-hairline rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold bg-[var(--semantic-warning)]/20 text-[var(--semantic-warning)] px-2 py-0.5 rounded-md">方式二</span>
              <span className="text-sm font-medium text-ink">直接輸入店家名稱</span>
            </div>
            <p className="text-xs text-ink-subtle leading-relaxed">
              輸入店家全名或關鍵字（例如「蘇草 salvia」、「鼎泰豐」），系統會自動搜尋比對。
            </p>
          </div>
        </div>
        <div className="flex items-start gap-2 text-xs text-ink-tertiary bg-primary/5 border border-primary/15 rounded-lg p-3">
          <HelpCircle className="w-3.5 h-3.5 text-primary shrink-0 mt-0.5" />
          <span>可同時輸入最多 3 間店家進行橫向比較，幫助你找到評論最真實的聚餐去處。</span>
        </div>
      </div>
    ),
  },
  {
    id: 2,
    icon: <Layers className="w-8 h-8 text-primary" />,
    title: '兩階段 AI 審計流程',
    subtitle: '規則引擎 + Gemini 語意審查，雙重保障',
    content: (
      <div className="space-y-3">
        {/* Stage 1 */}
        <div className="bg-surface-2 border border-hairline rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2.5">
            <span className="text-xs font-bold bg-[var(--semantic-danger)]/15 text-[var(--semantic-danger)] px-2 py-0.5 rounded-md">Stage 1</span>
            <span className="text-sm font-medium text-ink">規則引擎快速掃描</span>
          </div>
          <div className="space-y-1.5 text-xs text-ink-subtle leading-relaxed">
            <div className="flex items-start gap-2">
              <Gift className="w-3.5 h-3.5 text-[var(--semantic-danger)] shrink-0 mt-0.5" />
              <span><b className="text-ink">促銷型</b>：偵測「打卡送飲料」「好評換甜點」等利益誘因關鍵字</span>
            </div>
            <div className="flex items-start gap-2">
              <Copy className="w-3.5 h-3.5 text-[var(--semantic-warning)] shrink-0 mt-0.5" />
              <span><b className="text-ink">模板型</b>：比對跨評論的相似度，揪出重複敷衍的空泛用語</span>
            </div>
            <div className="flex items-start gap-2">
              <Star className="w-3.5 h-3.5 text-ink-subtle shrink-0 mt-0.5" />
              <span><b className="text-ink">時間爆發</b>：偵測短期內集中湧入的五星評論</span>
            </div>
          </div>
        </div>

        {/* Stage 2 */}
        <div className="bg-surface-2 border border-hairline rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2.5">
            <span className="text-xs font-bold bg-primary/15 text-primary px-2 py-0.5 rounded-md">Stage 2</span>
            <span className="text-sm font-medium text-ink">Gemini AI 語意深度分析</span>
          </div>
          <div className="space-y-1.5 text-xs text-ink-subtle leading-relaxed">
            <div className="flex items-start gap-2">
              <MessageSquareWarning className="w-3.5 h-3.5 text-primary shrink-0 mt-0.5" />
              <span><b className="text-ink">語意矛盾</b>：五星評分，內文卻有負向語意（「等很久但還行吧」）</span>
            </div>
            <div className="flex items-start gap-2">
              <HelpCircle className="w-3.5 h-3.5 text-ink-subtle shrink-0 mt-0.5" />
              <span>模糊評論（Stage 1 無法確定者）都會送 AI 進行語意二次判定</span>
            </div>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: 3,
    icon: <BarChart2 className="w-8 h-8 text-primary" />,
    title: '如何解讀結果？',
    subtitle: '三個核心指標，一眼看穿評論結構',
    content: (
      <div className="space-y-2.5 text-sm">
        {/* Rating comparison */}
        <div className="bg-surface-2 border border-hairline rounded-xl p-4 space-y-2">
          <span className="text-xs font-semibold text-ink-subtle uppercase tracking-wider">星等對比</span>
          <div className="flex items-center gap-3">
            <div className="text-center flex-1">
              <div className="text-base font-semibold text-ink-muted line-through decoration-ink-subtle/40">4.5★</div>
              <div className="text-[10px] text-ink-tertiary mt-0.5">Google 原始</div>
            </div>
            <ChevronRight className="w-4 h-4 text-ink-tertiary shrink-0" />
            <div className="text-center flex-1">
              <div className="text-base font-semibold text-primary">3.9★</div>
              <div className="text-[10px] text-ink-tertiary mt-0.5">校正後</div>
            </div>
          </div>
          <p className="text-xs text-ink-subtle leading-relaxed">
            移除結構異常評論後，以信任權重重新計算的真實評分。落差越大，代表水分越多。
          </p>
        </div>

        {/* Trust Score */}
        <div className="bg-surface-2 border border-hairline rounded-xl p-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-semibold text-ink-subtle uppercase tracking-wider">結構健康度</span>
            <span className="text-sm font-semibold text-[var(--semantic-warning)]">62/100</span>
          </div>
          <div className="w-full h-1.5 bg-surface-3 rounded-full overflow-hidden mb-2">
            <div className="h-full w-[62%] bg-[var(--semantic-warning)] rounded-full" />
          </div>
          <p className="text-xs text-ink-subtle">
            <span className="text-[var(--semantic-success)] font-medium">75+ 健康</span>
            {' · '}
            <span className="text-[var(--semantic-warning)] font-medium">50–74 留意</span>
            {' · '}
            <span className="text-[var(--semantic-danger)] font-medium">{'<50 警示'}</span>
          </p>
        </div>

        {/* Three issue types */}
        <div className="bg-surface-2 border border-hairline rounded-xl p-4">
          <span className="text-xs font-semibold text-ink-subtle uppercase tracking-wider block mb-2">三大異常類型</span>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="bg-surface-3 rounded-lg p-2">
              <Gift className="w-4 h-4 text-[var(--semantic-danger)] mx-auto mb-1" />
              <div className="font-medium text-ink">促銷型</div>
              <div className="text-[10px] text-ink-tertiary">利益誘因</div>
            </div>
            <div className="bg-surface-3 rounded-lg p-2">
              <Copy className="w-4 h-4 text-[var(--semantic-warning)] mx-auto mb-1" />
              <div className="font-medium text-ink">模板型</div>
              <div className="text-[10px] text-ink-tertiary">敷衍重複</div>
            </div>
            <div className="bg-surface-3 rounded-lg p-2">
              <MessageSquareWarning className="w-4 h-4 text-primary mx-auto mb-1" />
              <div className="font-medium text-ink">語意矛盾</div>
              <div className="text-[10px] text-ink-tertiary">評文不符</div>
            </div>
          </div>
        </div>
      </div>
    ),
  },
];

export function OnboardingModal({ onDismiss }: OnboardingModalProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [direction, setDirection] = useState<1 | -1>(1);

  const goNext = () => {
    if (currentStep === steps.length - 1) {
      onDismiss();
      return;
    }
    setDirection(1);
    setCurrentStep((s) => s + 1);
  };

  const goPrev = () => {
    if (currentStep === 0) return;
    setDirection(-1);
    setCurrentStep((s) => s - 1);
  };

  const step = steps[currentStep];

  const slideVariants = {
    enter: (dir: number) => ({ x: dir > 0 ? 60 : -60, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (dir: number) => ({ x: dir > 0 ? -60 : 60, opacity: 0 }),
  };

  return (
    /* Backdrop */
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onDismiss}
      />

      {/* Modal */}
      <motion.div
        initial={{ opacity: 0, scale: 0.94, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.94, y: 16 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-md bg-surface-1 border border-hairline-strong rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-4 border-b border-hairline">
          <div className="flex items-center gap-2">
            {step.icon}
            <div>
              <h2 className="text-base font-semibold text-ink tracking-[-0.4px] leading-tight">
                {step.title}
              </h2>
              <p className="text-xs text-ink-subtle mt-0.5">{step.subtitle}</p>
            </div>
          </div>
          <button
            onClick={onDismiss}
            className="text-ink-tertiary hover:text-ink-subtle transition-colors cursor-pointer p-1 rounded-lg hover:bg-surface-2"
            title="跳過教程"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step content */}
        <div className="relative overflow-hidden min-h-[300px]">
          <AnimatePresence custom={direction} mode="wait">
            <motion.div
              key={currentStep}
              custom={direction}
              variants={slideVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.2, ease: 'easeInOut' }}
              className="p-5"
            >
              {step.content}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Footer */}
        <div className="px-5 pb-5 pt-3 border-t border-hairline flex items-center justify-between gap-3">
          {/* Stepper dots */}
          <div className="flex items-center gap-1.5">
            {steps.map((s, i) => (
              <button
                key={s.id}
                onClick={() => {
                  setDirection(i > currentStep ? 1 : -1);
                  setCurrentStep(i);
                }}
                className={`transition-all duration-200 rounded-full cursor-pointer ${
                  i === currentStep
                    ? 'w-5 h-1.5 bg-primary'
                    : 'w-1.5 h-1.5 bg-surface-3 hover:bg-hairline-strong'
                }`}
              />
            ))}
          </div>

          {/* Navigation buttons */}
          <div className="flex items-center gap-2">
            {currentStep > 0 && (
              <button
                onClick={goPrev}
                className="flex items-center gap-1 text-xs font-medium text-ink-subtle bg-surface-2 hover:bg-surface-3 border border-hairline px-3 py-1.5 rounded-lg transition-colors cursor-pointer"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                上一步
              </button>
            )}
            <motion.button
              onClick={goNext}
              whileTap={{ scale: 0.97 }}
              className="flex items-center gap-1.5 text-xs font-medium text-white bg-primary hover:bg-primary-hover px-4 py-1.5 rounded-lg transition-colors cursor-pointer"
            >
              {currentStep === steps.length - 1 ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  開始使用
                </>
              ) : (
                <>
                  下一步
                  <ChevronRight className="w-3.5 h-3.5" />
                </>
              )}
            </motion.button>
          </div>
        </div>

        {/* Skip hint */}
        {currentStep < steps.length - 1 && (
          <div className="px-5 pb-4 text-center -mt-2">
            <button
              onClick={onDismiss}
              className="text-[11px] text-ink-tertiary hover:text-ink-subtle transition-colors cursor-pointer underline underline-offset-2"
            >
              跳過教程
            </button>
          </div>
        )}
      </motion.div>
    </div>
  );
}
