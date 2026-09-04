import { useState, useEffect } from 'react';
import { Github, ChevronDown, ChevronUp, MessageSquareText } from 'lucide-react';

interface VisitorStats {
  total: number;
  today: number;
  week: number;
}

export function Footer() {
  const [stats, setStats] = useState<VisitorStats | null>(null);
  const [creditsOpen, setCreditsOpen] = useState(false);

  useEffect(() => {
    fetch('/api/stats')
      .then(r => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  return (
    <footer className="border-t border-hairline bg-surface-1 mt-16">
      <div className="container mx-auto max-w-3xl px-4 py-8 text-xs text-ink-tertiary">
        {/* Top row */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div>
            <span className="text-sm font-medium text-ink-subtle">疑騙真星</span>
            <span className="text-ink-tertiary ml-1.5">TrueRating</span>
          </div>
          <div className="flex items-center gap-4">
            <a
              href="https://github.com/yiyi42205-ops/TTTTTTUUURREE"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 text-ink-subtle hover:text-ink transition-colors"
            >
              <Github className="w-3.5 h-3.5" />
              GitHub
            </a>
            <a
              href="https://docs.google.com/forms/d/e/1FAIpQLScXeQd2L43eDuMU_iv9GHGOedSkj3kKM-IEieeW6ieokHfA7g/viewform"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 text-ink-subtle hover:text-ink transition-colors"
            >
              <MessageSquareText className="w-3.5 h-3.5" />
              意見回饋
            </a>
            {stats && (
              <span className="font-mono tabular-nums">
                {stats.total.toLocaleString()} 次使用
              </span>
            )}
          </div>
        </div>

        {/* Credits */}
        <div className="mb-6">
          <button
            onClick={() => setCreditsOpen(!creditsOpen)}
            className="flex items-center gap-1 text-ink-subtle hover:text-ink transition-colors cursor-pointer"
          >
            致謝
            {creditsOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {creditsOpen && (
            <div className="mt-2 pl-3 border-l-2 border-hairline text-ink-tertiary leading-relaxed space-y-1">
              <p><span className="text-ink-subtle">114-2 Web App 開發第 C 組全體組員</span> — 初版開發</p>
              <p><span className="text-ink-subtle">Jake (MladenSrB)</span> — 協作開發</p>
            </div>
          )}
        </div>

        {/* Disclaimer */}
        <div className="space-y-1.5 leading-relaxed">
          <p className="font-medium text-ink-subtle">免責聲明</p>
          <p>本平台為學術研究專案，分析結果僅供消費決策參考，不代表對特定商家之品質評價。評論審計基於統計模型與 AI 語意分析，可能存在誤判。本站不對分析結果的準確性或完整性作任何保證。</p>
          <p className="mt-3">© 2026 TrueRating — 學術研究專案，非商業服務</p>
        </div>
      </div>
    </footer>
  );
}
