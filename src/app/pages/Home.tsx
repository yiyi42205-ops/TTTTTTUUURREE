import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Shield, Star, AlertTriangle, ArrowRight, Search, FileText, Sparkles, Clock, Info } from 'lucide-react';
import { useEffect } from 'react';
import { useIsPWA } from '../hooks/useIsPWA';
import { TutorialModal } from '../components/TutorialModal';

export function Home() {
  const navigate = useNavigate();
  const isPWA = useIsPWA();
  const [showTutorial, setShowTutorial] = useState(false);

  useEffect(() => {
    if (isPWA) {
      navigate('/analyzer', { replace: true });
    }
  }, [isPWA, navigate]);

  return (
    <div className="min-h-screen bg-background font-sans selection:bg-ink/10">
      {/* Navigation Header */}
      <header className="sticky top-0 z-50 bg-background border-b border-hairline px-4 md:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
          <div className="bg-ink text-background w-8 h-8 rounded flex items-center justify-center">
            <Shield className="w-4.5 h-4.5" />
          </div>
          <span className="font-sans font-semibold text-base text-ink tracking-[-0.4px]">
            疑騙真星
            <span className="text-ink-subtle font-normal text-sm ml-1.5">TrueRating</span>
          </span>
        </div>
        <button
          onClick={() => setShowTutorial(true)}
          className="w-7 h-7 rounded border border-hairline flex items-center justify-center text-ink-subtle hover:text-ink hover:border-hairline-strong transition-colors cursor-pointer"
          title="使用教學"
        >
          <Info className="w-3.5 h-3.5" />
        </button>
      </header>

      {showTutorial && <TutorialModal onClose={() => setShowTutorial(false)} />}

      {/* Hero Section */}
      <div className="container mx-auto px-4 py-16 max-w-5xl">
        <div className="text-center mb-16">
          <h1 className="text-4xl md:text-5xl font-semibold mb-4 text-ink tracking-[-1px] leading-tight">
            一鍵將評價「結構校正」<br className="md:hidden" />看清自然口碑
          </h1>

          <p className="text-base md:text-lg text-ink-subtle mb-10 max-w-xl mx-auto leading-relaxed">
            過濾打卡送小菜、行銷操作、敷衍模板等結構異常評論。<br />
            調用語意一致性大模型，還原 Google 地圖自然評分。
          </p>

          <button
            onClick={() => navigate('/analyzer')}
            className="bg-ink hover:bg-ink-muted text-background px-10 py-4 rounded text-lg font-medium transition-colors flex items-center gap-3 mx-auto cursor-pointer tracking-[-0.2px]"
          >
            進入比對分析儀
            <Search className="w-5 h-5" />
          </button>
        </div>

        {/* Features Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-16">
          <div className="bg-surface-1 rounded p-6 border border-hairline">
            <div className="w-10 h-10 bg-surface-3 rounded flex items-center justify-center mb-4">
              <Shield className="w-5 h-5 text-ink-subtle" />
            </div>
            <h3 className="text-base font-semibold mb-2 text-ink tracking-[-0.4px]">結構健康度評分</h3>
            <p className="text-sm text-ink-subtle leading-relaxed">
              基於發布時間密度、短評樣板以及贈送利益特徵，精準計算店家的結構健康度得分。
            </p>
          </div>

          <div className="bg-surface-1 rounded p-6 border border-hairline">
            <div className="w-10 h-10 bg-surface-3 rounded flex items-center justify-center mb-4">
              <Star className="w-5 h-5 text-ink-subtle" />
            </div>
            <h3 className="text-base font-semibold mb-2 text-ink tracking-[-0.4px]">自然有機評分</h3>
            <p className="text-sm text-ink-subtle leading-relaxed">
              自動過濾結構異常的 5 星好評，加入信譽懲罰係數，生成經演算法校正後的客觀用餐評分。
            </p>
          </div>

          <div className="bg-surface-1 rounded p-6 border border-hairline">
            <div className="w-10 h-10 bg-surface-3 rounded flex items-center justify-center mb-4">
              <FileText className="w-5 h-5 text-ink-subtle" />
            </div>
            <h3 className="text-base font-semibold mb-2 text-ink tracking-[-0.4px]">深度語意透視</h3>
            <p className="text-sm text-ink-subtle leading-relaxed">
              整合 LLM 思維鏈 (CoT) 剖析，指出每一則評價的隱形風險因素，提供最透明的審計日誌。
            </p>
          </div>
        </div>

        {/* Problem Statement Panel */}
        <div className="bg-surface-1 rounded p-8 border border-hairline mb-16">
          <h2 className="text-xl font-semibold mb-6 text-ink text-center tracking-[-0.4px]">
            常見的 Google 地圖結構異常評論手法
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex items-start gap-3 bg-surface-2 rounded p-4 border border-hairline">
              <Clock className="w-4 h-4 text-ink-subtle shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">時間爆發性集中</div>
                <div className="text-xs text-ink-subtle leading-relaxed">在數天至一週內短時間內集中湧入數十則內容相似的五星評價。</div>
              </div>
            </div>
            <div className="flex items-start gap-3 bg-surface-2 rounded p-4 border border-hairline">
              <FileText className="w-4 h-4 text-ink-subtle shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">敷衍語意模版</div>
                <div className="text-xs text-ink-subtle leading-relaxed">重複出現「服務很好，餐點好吃，推薦！」等缺乏具體餐點細節的空泛語句。</div>
              </div>
            </div>
            <div className="flex items-start gap-3 bg-surface-2 rounded p-4 border border-hairline">
              <Sparkles className="w-4 h-4 text-ink-subtle shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">打卡送小菜/優惠</div>
                <div className="text-xs text-ink-subtle leading-relaxed">提及「打卡送飲料」、「好評送甜點」等，以利益交換引導非自發性高分。</div>
              </div>
            </div>
            <div className="flex items-start gap-3 bg-surface-2 rounded p-4 border border-hairline">
              <AlertTriangle className="w-4 h-4 text-ink-subtle shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">評分與內文割裂</div>
                <div className="text-xs text-ink-subtle leading-relaxed">給予 5 星滿分，但文字卻包含「很難吃、态度差、等很久」等負向語意反饋。</div>
              </div>
            </div>
          </div>
        </div>

        {/* CTA Section */}
        <div className="text-center bg-surface-1 border border-hairline rounded p-12">
          <h2 className="text-2xl font-semibold mb-4 text-ink tracking-[-0.6px]">準備好辨別地圖上的評論結構了嗎？</h2>
          <p className="text-sm md:text-base mb-8 text-ink-subtle max-w-lg mx-auto leading-relaxed">
            系統支援一次輸入最多 3 間同類型店家進行「結構校正」與「自然口碑對比」，助您找到最實在的聚餐去處。
          </p>
          <button
            onClick={() => navigate('/analyzer')}
            className="bg-ink hover:bg-ink-muted text-background px-8 py-3.5 rounded text-base font-medium transition-colors flex items-center gap-2 mx-auto cursor-pointer"
          >
            立即啟動對比
            <ArrowRight className="w-5 h-5" />
          </button>
        </div>

      </div>
    </div>
  );
}
