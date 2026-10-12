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

// ── Steps ──

interface Step {
  bubbles: React.ReactNode;
}

const welcomeSearchStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        嗨！這裡幫你看穿 Google Maps 的灌水評價 👋
      </Bubble>
      <Bubble>
        貼上 Google Maps 網址，或直接打店名，送出就好。
      </Bubble>
      <Screenshot src="/tutorial/search.png" alt="搜尋示範" />
      <Bubble>
        <span className="font-medium">臺大周邊 1,500+ 家餐廳</span>已收錄，不用註冊、不用金鑰，直接查。
      </Bubble>
    </div>
  ),
};

const closingStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        報告會自己說話，看就懂。
      </Bubble>
      <Bubble>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded border border-hairline flex items-center justify-center shrink-0">
              <Key className="w-3 h-3 text-ink-subtle" />
            </div>
            <span>想查台大以外的店？點 <span className="font-medium">金鑰設定</span>（免費申請）</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded border border-hairline flex items-center justify-center shrink-0">
              <Info className="w-3 h-3 text-ink-subtle" />
            </div>
            <span>有問題？隨時點 <span className="font-medium">使用教學</span> 重看</span>
          </div>
        </div>
      </Bubble>
      <Bubble>
        去試試吧！🎉
      </Bubble>
    </div>
  ),
};

// ── Full-mode only: key setup guide (Apify + AI Key combined) ──

const keySetupStep: Step = {
  bubbles: (
    <div className="space-y-2.5">
      <Bubble>
        查<span className="font-medium">臺大以外</span>的店需要兩把金鑰，都<span className="font-medium">完全免費</span>：
      </Bubble>
      <Bubble>
        <div className="space-y-3">
          <div>
            <p className="font-medium mb-1">① Apify Token（爬評論用）</p>
            <ol className="list-decimal pl-4 space-y-0.5 text-xs">
              <li>前往 <a href="https://console.apify.com/sign-up" target="_blank" rel="noreferrer" className="underline text-primary">apify.com</a> → 用 Google 帳號註冊</li>
              <li>Settings → API & Integrations → 複製 Token</li>
            </ol>
          </div>
          <div>
            <p className="font-medium mb-1">② AI API Key（語意分析用）</p>
            <ol className="list-decimal pl-4 space-y-0.5 text-xs">
              <li>前往 <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="underline text-primary">AI Studio</a> → 點「Create API Key」</li>
              <li>複製產生的金鑰</li>
            </ol>
            <p className="text-ink-tertiary text-xs mt-1">也支援 <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer" className="underline">DeepSeek</a> 或任何 OpenAI 相容 API。</p>
          </div>
        </div>
      </Bubble>
      <Bubble>
        取得後點右上角 <Key className="w-3 h-3 inline" /> 貼入即可。查過的店會存入資料庫，之後<span className="font-medium">任何人再查都不需要金鑰</span>。
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
    ? [welcomeSearchStep, closingStep]
    : [welcomeSearchStep, keySetupStep, closingStep];

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
