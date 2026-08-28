import { useState } from 'react';
import { X, ChevronLeft, ChevronRight } from 'lucide-react';

interface TutorialModalProps {
  onClose: () => void;
}

const steps = [
  {
    title: '步驟一：輸入店家',
    content: (
      <div className="space-y-2">
        <p>在分析頁輸入 Google Maps 網址或直接打店名，最多同時比較 3 家。</p>
        <div className="bg-surface-2 border border-hairline rounded p-3 text-xs text-ink-subtle space-y-1.5">
          <p>支援的格式：</p>
          <ul className="list-disc pl-4 space-y-0.5">
            <li>Google Maps 網址（從瀏覽器複製）</li>
            <li>Google Maps 分享連結</li>
            <li>直接輸入店名（例如「蘇草salvia」）</li>
          </ul>
        </div>
      </div>
    ),
  },
  {
    title: '步驟二：等待分析',
    content: (
      <div className="space-y-2">
        <p>系統會自動執行兩階段審計：</p>
        <div className="space-y-2">
          <div className="bg-surface-2 border border-hairline rounded p-3 text-xs">
            <span className="font-medium text-ink">第一階段</span>
            <span className="text-ink-subtle"> — 規則引擎掃描促銷關鍵字、模板評論、時間異常</span>
          </div>
          <div className="bg-surface-2 border border-hairline rounded p-3 text-xs">
            <span className="font-medium text-ink">第二階段</span>
            <span className="text-ink-subtle"> — AI 語意分析模糊評論，判斷是否自然</span>
          </div>
        </div>
        <p className="text-xs text-ink-tertiary">資料庫已收錄的店家秒出結果，不需要 API 金鑰。</p>
      </div>
    ),
  },
  {
    title: '步驟三：看報告',
    content: (
      <div className="space-y-2">
        <p>報告從上到下依序是：</p>
        <ol className="list-decimal pl-4 space-y-1 text-sm">
          <li><span className="font-medium">評分校正</span> — 原始 vs. 過濾後的星級</li>
          <li><span className="font-medium">評論成分</span> — 促銷型、模板型、語意矛盾各佔多少</li>
          <li><span className="font-medium">星級分佈</span> — 校正前後的對比圖</li>
          <li><span className="font-medium">逐條檢核</span> — 展開看每則評論的判定理由</li>
        </ol>
      </div>
    ),
  },
  {
    title: '未收錄的店家',
    content: (
      <div className="space-y-2">
        <p>
          如果查詢的店家不在資料庫中，需要即時爬取評論。
          系統會請你提供自己的 <span className="font-medium">Apify Token</span>。
        </p>
        <div className="bg-surface-2 border border-hairline rounded p-3 text-xs space-y-2">
          <p className="font-medium text-ink">如何取得 Apify Token（免費）：</p>
          <ol className="list-decimal pl-4 space-y-1 text-ink-subtle">
            <li>前往 <a href="https://console.apify.com/sign-up" target="_blank" rel="noreferrer" className="underline text-ink">apify.com</a> 註冊帳號</li>
            <li>進入 Settings → Integrations</li>
            <li>複製 Personal API Token</li>
            <li>貼回本站的輸入框</li>
          </ol>
          <p className="text-ink-tertiary">免費帳號每月有 $5 USD 額度，約可查 100 家店。</p>
        </div>
      </div>
    ),
  },
  {
    title: 'AI 問答功能（選用）',
    content: (
      <div className="space-y-2">
        <p>
          報告底部可以向 AI 提問（例如「這家店推薦點什麼？」）。
          此功能需要你自己的 <span className="font-medium">Gemini API Key</span>。
        </p>
        <div className="bg-surface-2 border border-hairline rounded p-3 text-xs space-y-2">
          <p className="font-medium text-ink">如何取得 Gemini API Key（免費）：</p>
          <ol className="list-decimal pl-4 space-y-1 text-ink-subtle">
            <li>前往 <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="underline text-ink">Google AI Studio</a></li>
            <li>點「Create API Key」</li>
            <li>複製金鑰，貼到本站設定頁</li>
          </ol>
          <p className="text-ink-tertiary">免費方案每分鐘 15 次請求，日常使用足夠。</p>
        </div>
      </div>
    ),
  },
];

export function TutorialModal({ onClose }: TutorialModalProps) {
  const [step, setStep] = useState(0);
  const current = steps[step];
  const isLast = step === steps.length - 1;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/40 px-4">
      <div className="bg-background border border-hairline-strong rounded max-w-md w-full shadow-lg">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline">
          <span className="text-xs text-ink-tertiary font-mono tabular-nums">
            {step + 1} / {steps.length}
          </span>
          <button
            onClick={onClose}
            className="text-ink-subtle hover:text-ink cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="px-5 py-5">
          <h3 className="text-sm font-semibold text-ink mb-3">{current.title}</h3>
          <div className="text-sm text-ink-muted leading-relaxed">
            {current.content}
          </div>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between px-5 py-3.5 border-t border-hairline">
          <button
            onClick={() => setStep(s => s - 1)}
            disabled={step === 0}
            className="flex items-center gap-1 text-xs text-ink-subtle hover:text-ink disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            上一步
          </button>

          {isLast ? (
            <button
              onClick={onClose}
              className="bg-ink hover:bg-ink-muted text-background px-5 py-1.5 rounded text-xs font-medium cursor-pointer transition-colors"
            >
              完成
            </button>
          ) : (
            <button
              onClick={() => setStep(s => s + 1)}
              className="flex items-center gap-1 bg-ink hover:bg-ink-muted text-background px-4 py-1.5 rounded text-xs font-medium cursor-pointer transition-colors"
            >
              下一步
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
