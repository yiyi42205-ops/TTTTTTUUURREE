import { useState } from 'react';
import { X, ChevronLeft, ChevronRight, MapPin, Globe } from 'lucide-react';

export const TUTORIAL_STORAGE_KEY = 'truerating_tutorial_completed';

interface TutorialModalProps {
  onClose: () => void;
}

type Path = 'near_ntu' | 'other' | null;

const introStep = {
  title: '歡迎使用疑騙真星 TrueRating',
  content: (
    <div className="space-y-3">
      <p>
        本站分析 Google Maps 餐廳評論的真實性，幫你看穿灌水評價。
        資料庫目前已收錄<span className="font-medium text-ink">臺大周邊 1,500+ 家餐廳</span>，其他區域也會陸續更新。
      </p>
      <p className="font-medium text-ink">你想查的店在哪裡？</p>
    </div>
  ),
};

const nearNtuSteps = [
  {
    title: '臺大附近的店 — 直接查！',
    content: (
      <div className="space-y-2">
        <p>
          資料庫已收錄的店家<span className="font-medium text-ink">不需要任何 API 金鑰</span>，輸入店名或 Google Maps 網址即可秒出完整報告，包含 AI 語意審計結果。
        </p>
        <div className="bg-surface-2 border border-hairline rounded p-3 text-xs text-ink-subtle space-y-1.5">
          <p>支援的輸入格式：</p>
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
    title: '看懂報告',
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
];

const otherSteps = [
  {
    title: '其他地區的店 — 需要兩把金鑰',
    content: (
      <div className="space-y-2">
        <p>
          不在資料庫中的店家需要即時爬取評論並進行 AI 語意審計，
          系統會請你提供：
        </p>
        <div className="bg-surface-2 border border-hairline rounded p-3 text-xs space-y-2">
          <p className="font-medium text-ink">1. Apify Token — 爬取評論（免費）</p>
          <ol className="list-decimal pl-4 space-y-1 text-ink-subtle">
            <li>前往 <a href="https://console.apify.com/sign-up" target="_blank" rel="noreferrer" className="underline text-ink">apify.com</a> 註冊帳號</li>
            <li>進入 Settings → Integrations</li>
            <li>複製 Personal API Token</li>
          </ol>
          <p className="text-ink-tertiary">免費帳號每月有 $5 USD 額度，約可查 100 家店。</p>
        </div>
        <div className="bg-surface-2 border border-hairline rounded p-3 text-xs space-y-2">
          <p className="font-medium text-ink">2. AI API Key — 語意審計（免費）</p>
          <p className="text-ink-subtle">支援以下任一服務：</p>
          <ul className="list-disc pl-4 space-y-1 text-ink-subtle">
            <li><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="underline text-ink">Gemini</a> — 免費方案每分鐘 15 次請求</li>
            <li><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer" className="underline text-ink">DeepSeek</a></li>
            <li>任何 OpenAI 相容 API</li>
          </ul>
          <p className="text-ink-tertiary">取得後貼到本站設定頁即可。查過一次的店會存入資料庫，之後不再需要金鑰。</p>
        </div>
      </div>
    ),
  },
  {
    title: '看懂報告',
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
];

const aiStepNearNtu = {
  title: 'AI 問答功能（選用）',
  content: (
    <div className="space-y-2">
      <p>
        報告底部可以向 AI 提問（例如「這家店推薦點什麼？」）。
        此功能需要你自己的 <span className="font-medium">AI API Key</span>。
      </p>
      <div className="bg-surface-2 border border-hairline rounded p-3 text-xs space-y-2">
        <p className="font-medium text-ink">支援的 AI 服務（擇一即可）：</p>
        <ul className="list-disc pl-4 space-y-1 text-ink-subtle">
          <li><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="underline text-ink">Gemini</a> — 免費方案每分鐘 15 次請求</li>
          <li><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer" className="underline text-ink">DeepSeek</a></li>
          <li>任何 OpenAI 相容 API</li>
        </ul>
        <p className="text-ink-tertiary">取得金鑰後，貼到本站設定頁即可使用。審計報告本身不需要金鑰。</p>
      </div>
    </div>
  ),
};

const aiStepOther = {
  title: 'AI 問答功能（選用）',
  content: (
    <div className="space-y-2">
      <p>
        報告底部可以向 AI 提問（例如「這家店推薦點什麼？」）。
        如果你已在上一步填入 AI API Key，問答功能會直接可用。
      </p>
    </div>
  ),
};

export function TutorialModal({ onClose }: TutorialModalProps) {
  const [path, setPath] = useState<Path>(null);
  const [step, setStep] = useState(0);

  const handleSelectPath = (selected: Path) => {
    setPath(selected);
    setStep(0);
  };

  const handleClose = () => {
    localStorage.setItem(TUTORIAL_STORAGE_KEY, '1');
    onClose();
  };

  // Intro screen — path selection
  if (path === null) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/40 px-4">
        <div className="bg-background border border-hairline-strong rounded max-w-md w-full shadow-lg">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline">
            <span className="text-xs text-ink-tertiary font-mono">教學導覽</span>
            <button onClick={handleClose} className="text-ink-subtle hover:text-ink cursor-pointer">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="px-5 py-5">
            <h3 className="text-sm font-semibold text-ink mb-3">{introStep.title}</h3>
            <div className="text-sm text-ink-muted leading-relaxed mb-4">{introStep.content}</div>
            <div className="space-y-2.5">
              <button
                onClick={() => handleSelectPath('near_ntu')}
                className="w-full flex items-center gap-3 p-3.5 rounded-lg border border-hairline hover:border-primary/50 hover:bg-primary/5 transition-all cursor-pointer text-left"
              >
                <MapPin className="w-5 h-5 text-primary shrink-0" />
                <div>
                  <p className="text-sm font-medium text-ink">在臺大附近</p>
                  <p className="text-xs text-ink-subtle">直接查，不需要任何金鑰</p>
                </div>
              </button>
              <button
                onClick={() => handleSelectPath('other')}
                className="w-full flex items-center gap-3 p-3.5 rounded-lg border border-hairline hover:border-primary/50 hover:bg-primary/5 transition-all cursor-pointer text-left"
              >
                <Globe className="w-5 h-5 text-ink-subtle shrink-0" />
                <div>
                  <p className="text-sm font-medium text-ink">不在臺大附近</p>
                  <p className="text-xs text-ink-subtle">需要免費的 Apify Token 即時爬取</p>
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Path-specific steps + path-specific AI step at the end
  const pathSteps = path === 'near_ntu' ? nearNtuSteps : otherSteps;
  const aiStep = path === 'near_ntu' ? aiStepNearNtu : aiStepOther;
  const allSteps = [...pathSteps, aiStep];
  const current = allSteps[step];
  const isLast = step === allSteps.length - 1;
  const totalWithIntro = allSteps.length + 1; // +1 for the intro we already passed

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/40 px-4">
      <div className="bg-background border border-hairline-strong rounded max-w-md w-full shadow-lg">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline">
          <span className="text-xs text-ink-tertiary font-mono tabular-nums">
            {step + 2} / {totalWithIntro}
          </span>
          <button onClick={handleClose} className="text-ink-subtle hover:text-ink cursor-pointer">
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
            onClick={() => step === 0 ? setPath(null) : setStep(s => s - 1)}
            className="flex items-center gap-1 text-xs text-ink-subtle hover:text-ink cursor-pointer"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            上一步
          </button>

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
