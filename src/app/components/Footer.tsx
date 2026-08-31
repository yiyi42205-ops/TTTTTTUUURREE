import { useState, useEffect } from 'react';
import { Github, ChevronDown, ChevronUp } from 'lucide-react';

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
            <div className="mt-2 pl-3 border-l-2 border-hairline text-ink-tertiary leading-relaxed">
              <p><span className="text-ink-subtle">Jake (MladenSrB)</span> — 協作開發</p>
            </div>
          )}
        </div>

        {/* Bottom */}
        <div className="space-y-1.5 leading-relaxed">
          <p>© 2026 TrueRating. 本平台為學術研究專案，不提供任何商業服務保證。</p>
          <p>分析結果僅供消費決策參考，不代表對特定商家之品質評價。</p>
        </div>
      </div>
    </footer>
  );
}
