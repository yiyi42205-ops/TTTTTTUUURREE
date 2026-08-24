import { motion } from 'motion/react';
import { useNavigate } from 'react-router';
import { Shield, Star, AlertTriangle, ArrowRight, Search, FileText, Sparkles, Clock } from 'lucide-react';
import { useEffect } from 'react';
import { useIsPWA } from '../hooks/useIsPWA';

export function Home() {
  const navigate = useNavigate();

  const isPWA = useIsPWA();

  useEffect(() => {
    if (isPWA) {
      navigate('/analyzer', { replace: true });
    }
  }, [isPWA, navigate]);

  return (
    <div className="min-h-screen bg-background font-sans selection:bg-primary/20">
      {/* Navigation Header */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-background/80 border-b border-hairline px-4 md:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
          <div className="bg-primary text-white w-8 h-8 rounded-lg flex items-center justify-center">
            <Shield className="w-4.5 h-4.5 text-white" />
          </div>
          <span className="font-sans font-semibold text-base text-ink tracking-[-0.4px]">
            疑騙真星
            <span className="text-ink-subtle font-normal text-sm ml-1.5">TrueRating</span>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] md:text-xs bg-surface-2 border border-hairline text-ink-subtle font-medium px-2.5 py-1 rounded-lg flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
            二階段 AI 混合審計引擎 v1.2
          </span>
        </div>
      </header>

      {/* Hero Section */}
      <div className="container mx-auto px-4 py-16 max-w-5xl">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h1 className="text-4xl md:text-5xl font-semibold mb-4 text-ink tracking-[-1px] leading-tight">
            一鍵將評價「結構校正」<br className="md:hidden" />看清自然口碑
          </h1>

          <p className="text-base md:text-lg text-ink-subtle mb-10 max-w-xl mx-auto leading-relaxed">
            過濾打卡送小菜、行銷操作、敷衍模板等結構異常評論。<br />
            調用語意一致性大模型，還原 Google 地圖自然評分。
          </p>

          <motion.button
            onClick={() => navigate('/analyzer')}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.98 }}
            className="bg-primary hover:bg-primary-hover text-white px-10 py-4 rounded-lg text-lg font-medium transition-all flex items-center gap-3 mx-auto cursor-pointer tracking-[-0.2px]"
          >
            進入比對分析儀
            <Search className="w-5 h-5" />
          </motion.button>
        </motion.div>

        {/* Features Grid */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-16"
        >
          {/* Card 1 */}
          <div className="bg-surface-1 rounded-xl p-6 border border-hairline flex flex-col items-center text-center">
            <div className="w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center mb-4">
              <Shield className="w-6 h-6 text-primary" />
            </div>
            <h3 className="text-lg font-semibold mb-2 text-ink tracking-[-0.4px]">結構健康度評分</h3>
            <p className="text-sm text-ink-subtle leading-relaxed">
              基於發布時間密度、短評樣板以及贈送利益特徵，精準計算店家的結構健康度得分。
            </p>
          </div>

          {/* Card 2 */}
          <div className="bg-surface-1 rounded-xl p-6 border border-hairline flex flex-col items-center text-center">
            <div className="w-12 h-12 bg-[var(--semantic-warning)]/10 rounded-xl flex items-center justify-center mb-4">
              <Star className="w-6 h-6 text-[var(--semantic-warning)]" />
            </div>
            <h3 className="text-lg font-semibold mb-2 text-ink tracking-[-0.4px]">自然有機評分</h3>
            <p className="text-sm text-ink-subtle leading-relaxed">
              自動過濾結構異常的 5 星好評，加入信譽懲罰係數，生成經演算法校正後的客觀用餐評分。
            </p>
          </div>

          {/* Card 3 */}
          <div className="bg-surface-1 rounded-xl p-6 border border-hairline flex flex-col items-center text-center">
            <div className="w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center mb-4">
              <FileText className="w-6 h-6 text-primary" />
            </div>
            <h3 className="text-lg font-semibold mb-2 text-ink tracking-[-0.4px]">深度語意透視</h3>
            <p className="text-sm text-ink-subtle leading-relaxed">
              整合 LLM 思維鏈 (CoT) 剖析，指出每一則評價的隱形風險因素，提供最透明的審計日誌。
            </p>
          </div>
        </motion.div>

        {/* Problem Statement Panel */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="bg-surface-1 rounded-xl p-8 border border-hairline mb-16"
        >
          <h2 className="text-xl font-semibold mb-6 text-ink text-center tracking-[-0.4px] flex items-center justify-center gap-2">
            <Shield className="w-5 h-5 text-primary" />
            常見的 Google 地圖結構異常評論手法
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex items-start gap-3 bg-surface-2 rounded-xl p-4 border border-hairline">
              <Clock className="w-4 h-4 text-ink-subtle shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">時間爆發性集中</div>
                <div className="text-xs text-ink-subtle leading-relaxed">在數天至一週內短時間內集中湧入數十則內容相似的五星評價。</div>
              </div>
            </div>
            <div className="flex items-start gap-3 bg-surface-2 rounded-xl p-4 border border-hairline">
              <FileText className="w-4 h-4 text-ink-subtle shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">敷衍語意模版</div>
                <div className="text-xs text-ink-subtle leading-relaxed">重複出現「服務很好，餐點好吃，推薦！」等缺乏具體餐點細節的空泛語句。</div>
              </div>
            </div>
            <div className="flex items-start gap-3 bg-surface-2 rounded-xl p-4 border border-hairline">
              <Sparkles className="w-4 h-4 text-[var(--semantic-warning)] shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">打卡送小菜/優惠</div>
                <div className="text-xs text-ink-subtle leading-relaxed">提及「打卡送飲料」、「好評送甜點」等，以利益交換引導非自發性高分。</div>
              </div>
            </div>
            <div className="flex items-start gap-3 bg-surface-2 rounded-xl p-4 border border-hairline">
              <AlertTriangle className="w-4 h-4 text-[var(--semantic-warning)] shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink text-sm mb-1">評分與內文割裂</div>
                <div className="text-xs text-ink-subtle leading-relaxed">給予 5 星滿分，但文字卻包含「很難吃、态度差、等很久」等負向語意反饋。</div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* CTA Section */}
        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.5 }}
          className="text-center bg-surface-1 border border-hairline rounded-xl p-12 relative overflow-hidden"
        >
          <div className="absolute right-0 top-0 translate-x-16 -translate-y-16 w-48 h-48 bg-primary/5 rounded-full blur-3xl"></div>
          <h2 className="text-2xl font-semibold mb-4 text-ink tracking-[-0.6px]">準備好辨別地圖上的評論結構了嗎？</h2>
          <p className="text-sm md:text-base mb-8 text-ink-subtle max-w-lg mx-auto leading-relaxed">
            系統支援一次輸入最多 3 間同類型店家進行「結構校正」與「自然口碑對比」，助您找到最實在的聚餐去處。
          </p>
          <motion.button
            onClick={() => navigate('/analyzer')}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.98 }}
            className="bg-primary hover:bg-primary-hover text-white px-8 py-3.5 rounded-lg text-base font-medium transition-all flex items-center gap-2 mx-auto cursor-pointer"
          >
            立即啟動對比
            <ArrowRight className="w-5 h-5" />
          </motion.button>
        </motion.div>

        {/* Footnote */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8 }}
          className="mt-12 text-center text-[10px] text-ink-tertiary leading-relaxed max-w-3xl mx-auto"
        >
          <p>免責聲明：本平台基於自然語言處理 (NLP) 演算法及時間序列分析對 Google Maps 評論數據集進行行為模式判定。分析報告旨在揭露異常資料及提高消費市場透明度，所提供評分結果僅供使用者個人消費決策之參考，不代表本平台對特定商家之衛生、品質或服務水準之保證，亦不對因此產生之任何消費爭議承擔法律責任。</p>
        </motion.div>
      </div>
    </div>
  );
}
