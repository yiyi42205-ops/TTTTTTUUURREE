import { useState } from 'react';
import { X, ChevronLeft, ChevronRight, Key, Info } from 'lucide-react';

export const TUTORIAL_STORAGE_KEY = 'truerating_tutorial_completed';

interface TutorialModalProps {
  onClose: () => void;
  mode?: 'first-time' | 'full';
}

// ── Chat bubble component ──

function Bubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-surface-2 border border-hairline rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm text-ink leading-relaxed max-w-[90%]">
      {children}
    </div>
  );
}

function Screenshot({ src, alt }: { src: string; alt: string }) {
  return (
    <img
      src={src}
      alt={alt}
      className="max-w-[90%] rounded-lg border border-hairline shadow-sm"
      onError={e => (e.currentTarget.style.display = 'none')}
    />
  );
}

// ── Steps as chat conversations ──

interface Step {
  bubbles: React.ReactNode;
}

const welcomeStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        嗨！歡迎使用<span className="font-medium">疑騙真星 TrueRating</span> 👋
      </Bubble>
      <Bubble>
        我們幫你分析 Google Maps 餐廳評論的真實性，看穿灌水評價。
      </Bubble>
      <Bubble>
        資料庫已收錄 <span className="font-medium">臺大周邊 1,500+ 家餐廳</span>，這些店<span className="font-medium">不需要任何金鑰或註冊</span>，直接查就好。
      </Bubble>
      <Bubble>
        來，用「男一快餐」示範一下 ↓
      </Bubble>
    </div>
  ),
};

const searchStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        在搜尋欄貼上 Google Maps 網址，或直接打店名就行。
      </Bubble>
      <Screenshot src="/tutorial/search.png" alt="搜尋示範" />
      <Bubble>
        支援瀏覽器網址、分享連結、或直接輸入「男一快餐」。
      </Bubble>
    </div>
  ),
};

const reportStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        送出後秒出報告 👇
      </Bubble>
      <Screenshot src="/tutorial/report.png" alt="審計報告" />
      <Bubble>
        上面告訴你：
      </Bubble>
      <Bubble>
        <span className="font-medium">評分校正</span> — 過濾假評論後的真實星級{'\n'}
        <span className="font-medium">結構健康度</span> — 評論結構的自然程度{'\n'}
        <span className="font-medium">評論成分</span> — 促銷型、模板型、語意矛盾各佔多少
      </Bubble>
    </div>
  ),
};

const summaryStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        往下滑會看到 <span className="font-medium">AI 總結</span> 👇
      </Bubble>
      <Screenshot src="/tutorial/summary.png" alt="AI 總結" />
      <Bubble>
        <span className="font-medium">避雷提示</span>幫你整理出真實評論中反覆被提到的缺點，每條都附來源。
      </Bubble>
    </div>
  ),
};

const reviewStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        再往下是<span className="font-medium">逐條檢核</span>，每則評論都有判定結果和信心度 👇
      </Bubble>
      <Screenshot src="/tutorial/review.png" alt="逐條檢核" />
      <Bubble>
        可以篩選只看洗評的、自然的、或某一階段的結果。
      </Bubble>
    </div>
  ),
};

const qaStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        最下面可以向 AI 提問，例如「推薦什麼菜？」「服務態度如何？」
      </Bubble>
      <Screenshot src="/tutorial/qa.png" alt="AI 問答" />
      <Bubble>
        這個功能需要你自己的 AI API Key（免費申請），點右上角 <Key className="w-3 h-3 inline" /> 設定。
      </Bubble>
    </div>
  ),
};

const toolbarStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        最後提醒一下，右上角有兩個按鈕隨時可用：
      </Bubble>
      <Bubble>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded border border-hairline flex items-center justify-center shrink-0">
              <Key className="w-3 h-3 text-ink-subtle" />
            </div>
            <span><span className="font-medium">金鑰設定</span> — 管理 API 金鑰</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded border border-hairline flex items-center justify-center shrink-0">
              <Info className="w-3 h-3 text-ink-subtle" />
            </div>
            <span><span className="font-medium">使用教學</span> — 重新開啟這份導覽</span>
          </div>
        </div>
      </Bubble>
      <Bubble>
        好了，去試試吧！🎉
      </Bubble>
    </div>
  ),
};

// ── Full-mode only: key setup guides ──

const apifyStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        如果你想查<span className="font-medium">臺大以外</span>的店家，需要提供 Apify Token 來即時爬取評論。
      </Bubble>
      <Bubble>
        <span className="font-medium">完全免費，不需要信用卡。</span>申請步驟：
      </Bubble>
      <Bubble>
        <ol className="list-decimal pl-4 space-y-1">
          <li>前往 <a href="https://console.apify.com/sign-up" target="_blank" rel="noreferrer" className="underline text-primary">apify.com</a> 註冊（Google 一鍵登入）</li>
          <li>進入 Settings → Integrations</li>
          <li>複製 Personal API Token</li>
        </ol>
      </Bubble>
      <Bubble>
        免費帳號每月 $5 USD 額度，大約可以查 100 家店。查過的店會自動存入資料庫，之後<span className="font-medium">任何人再查都不需要金鑰</span>。
      </Bubble>
    </div>
  ),
};

const aiKeyStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        即時爬取的店還需要一把 <span className="font-medium">AI API Key</span> 進行語意審計，一樣<span className="font-medium">完全免費</span>。
      </Bubble>
      <Bubble>
        <div className="space-y-1.5">
          <p className="font-medium">支援的 AI 服務（擇一即可）：</p>
          <ul className="list-disc pl-4 space-y-0.5">
            <li><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="underline text-primary">Gemini</a> — 推薦，免費每分鐘 15 次</li>
            <li><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer" className="underline text-primary">DeepSeek</a></li>
            <li>任何 OpenAI 相容 API</li>
          </ul>
        </div>
      </Bubble>
      <Bubble>
        取得後點右上角 <Key className="w-3 h-3 inline" /> 貼入即可。已經收錄的台大店家<span className="font-medium">不需要這些金鑰</span>。
      </Bubble>
    </div>
  ),
};

// ── Component ──

export function TutorialModal({ onClose, mode = 'first-time' }: TutorialModalProps) {
  const [step, setStep] = useState(0);

  const handleClose = () => {
    localStorage.setItem(TUTORIAL_STORAGE_KEY, '1');
    onClose();
  };

  const steps: Step[] = mode === 'first-time'
    ? [welcomeStep, searchStep, reportStep, summaryStep, reviewStep, toolbarStep]
    : [welcomeStep, searchStep, reportStep, summaryStep, reviewStep, qaStep, apifyStep, aiKeyStep, toolbarStep];

  const current = steps[step];
  const isFirst = step === 0;
  const isLast = step === steps.length - 1;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/40 px-4">
      <div className="bg-background border border-hairline-strong rounded-xl max-w-md w-full shadow-lg max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-hairline shrink-0">
          <span className="text-xs text-ink-tertiary font-mono tabular-nums">
            {step + 1} / {steps.length}
          </span>
          <button onClick={handleClose} className="text-ink-subtle hover:text-ink cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Chat content — scrollable */}
        <div className="px-4 py-5 overflow-y-auto flex-1">
          {current.bubbles}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-hairline shrink-0">
          {isFirst ? (
            <span />
          ) : (
            <button
              onClick={() => setStep(s => s - 1)}
              className="flex items-center gap-1 text-xs text-ink-subtle hover:text-ink cursor-pointer"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              上一步
            </button>
          )}

          {isLast ? (
            <button
              onClick={handleClose}
              className="bg-ink hover:bg-ink-muted text-background px-5 py-1.5 rounded text-xs font-medium cursor-pointer transition-colors"
            >
              開始使用
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
