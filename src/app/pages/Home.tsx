import { motion } from 'motion/react';
import { useNavigate } from 'react-router';
import { Shield, Star, AlertTriangle, ArrowRight, Search, FileText, Sparkles, CheckCircle, Clock } from 'lucide-react';
import { useEffect } from 'react';

export function Home() {
  const navigate = useNavigate();

  useEffect(() => {
    const isPWA = window.matchMedia('(display-mode: standalone)').matches 
               || (window.navigator as any).standalone === true
               || window.matchMedia('(max-width: 767px)').matches;
    if (isPWA) {
      navigate('/analyzer', { replace: true });
    }
  }, [navigate]);

  return (
    <div className="min-h-screen bg-[#f5f1e8] font-sans selection:bg-[#6b8e7f]/20">
      {/* Premium Navigation Header */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-[#f5f1e8]/80 border-b border-[#d4c5b0]/30 px-4 md:px-8 py-3.5 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
          <div className="bg-[#6b8e7f] text-white w-9 h-9 rounded-xl border-2 border-[#4a5d52] font-black text-base shadow-sm flex items-center justify-center">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <span className="font-display font-black text-lg text-[#4a5d52] tracking-tight">
            疑騙真星 <span className="text-[#6b8e7f] font-sans font-bold text-sm bg-white border border-[#d4c5b0]/60 px-1.5 py-0.5 rounded-md ml-1">TrueRating</span>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] md:text-xs bg-[#6b8e7f]/10 border border-[#6b8e7f]/30 text-[#4a5d52] font-black px-2.5 py-1 rounded-full flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#6b8e7f] animate-ping"></span>
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


          <h1 className="text-4xl md:text-5xl font-black mb-4 text-[#4a5d52] font-display tracking-tight leading-tight">
            一鍵將評價「脫水」<br className="md:hidden" />看清真實口碑
          </h1>
          
          <p className="text-base md:text-lg text-[#6b8e7f] mb-10 max-w-xl mx-auto leading-relaxed font-medium">
            過濾打卡送小菜、行銷灌水、敷衍模板等虛假好評。<br />
            調用語意一致性大模型，還原 Google 地圖真實星級！
          </p>

          <motion.button
            onClick={() => navigate('/analyzer')}
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-[#e8c547] text-[#4a5d52] px-10 py-4 rounded-full text-lg font-black shadow-[4px_4px_0px_0px_#4a5d52] hover:shadow-[6px_6px_0px_0px_#4a5d52] transition-all border-4 border-[#4a5d52] flex items-center gap-3 mx-auto cursor-pointer font-display tracking-wide"
          >
            進入比對分析儀
            <Search className="w-6 h-6 text-[#4a5d52] stroke-[3]" />
          </motion.button>
        </motion.div>

        {/* Features Grid - Chunky Tactile Blocks */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16"
        >
          {/* Card 1 */}
          <motion.div 
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-white rounded-3xl p-6 border-3 border-[#4a5d52] shadow-tactile hover:shadow-[6px_6px_0px_0px_#4a5d52] transition-all duration-200 flex flex-col items-center text-center cursor-pointer"
          >
            <div className="w-14 h-14 bg-[#6b8e7f]/10 border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] rounded-2xl flex items-center justify-center mb-5 text-[#6b8e7f]">
              <Shield className="w-7 h-7 stroke-[2.5]" />
            </div>
            <h3 className="text-xl font-extrabold mb-3 text-[#4a5d52] font-display">信任度評分</h3>
            <p className="text-xs text-[#6b8e7f] leading-relaxed font-bold">
              基於發布時間密度、短評樣板以及贈送利益特徵，精準計算店家的防灌水真實度得分。
            </p>
          </motion.div>

          {/* Card 2 */}
          <motion.div 
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-white rounded-3xl p-6 border-3 border-[#4a5d52] shadow-tactile hover:shadow-[6px_6px_0px_0px_#4a5d52] transition-all duration-200 flex flex-col items-center text-center cursor-pointer"
          >
            <div className="w-14 h-14 bg-[#e8c547]/10 border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] rounded-2xl flex items-center justify-center mb-5 text-[#e8c547]">
              <Star className="w-7 h-7 stroke-[2.5]" />
            </div>
            <h3 className="text-xl font-extrabold mb-3 text-[#4a5d52] font-display">真實有機評分</h3>
            <p className="text-xs text-[#6b8e7f] leading-relaxed font-bold">
              自動刨除虛假的 5 星好評，加入信譽懲罰係數，生成經演算法矯正後的客觀用餐評分。
            </p>
          </motion.div>

          {/* Card 3 */}
          <motion.div 
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-white rounded-3xl p-6 border-3 border-[#4a5d52] shadow-tactile hover:shadow-[6px_6px_0px_0px_#4a5d52] transition-all duration-200 flex flex-col items-center text-center cursor-pointer"
          >
            <div className="w-14 h-14 bg-[#5b7a9f]/10 border-2 border-[#4a5d52] shadow-[2px_2px_0px_0px_#4a5d52] rounded-2xl flex items-center justify-center mb-5 text-[#5b7a9f]">
              <FileText className="w-7 h-7 stroke-[2.5]" />
            </div>
            <h3 className="text-xl font-extrabold mb-3 text-[#4a5d52] font-display">深度語意透視</h3>
            <p className="text-xs text-[#6b8e7f] leading-relaxed font-bold">
              整合 LLM 思維鏈 (CoT) 剖析，指出每一則評價的隱形風險因素，提供最透明的審計日誌。
            </p>
          </motion.div>
        </motion.div>

        {/* Problem Statement Panel */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="bg-white rounded-[32px] p-8 shadow-tactile border-3 border-[#4a5d52] mb-16"
        >
          <h2 className="text-2xl font-black mb-8 text-[#4a5d52] text-center font-display flex items-center justify-center gap-2.5">
            <Shield className="w-6 h-6 text-[#6b8e7f] stroke-[2.5]" />
            常見的 Google 地圖洗評手法
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="flex items-start gap-4 bg-[#f5f1e8] hover:bg-white rounded-2xl p-5 border-2 border-[#4a5d52] shadow-tactile-sm hover:shadow-tactile transition-all hover:-translate-y-1 cursor-default">
              <Clock className="w-5 h-5 text-[#6b8e7f] shrink-0 mt-0.5" />
              <div>
                <div className="font-extrabold text-[#4a5d52] text-sm mb-1">時間爆發性集中</div>
                <div className="text-xs text-[#6b8e7f] leading-relaxed">在數天至一週內短時間內集中湧入數十則內容相似的五星評價。</div>
              </div>
            </div>
            <div className="flex items-start gap-4 bg-[#f5f1e8] hover:bg-white rounded-2xl p-5 border-2 border-[#4a5d52] shadow-tactile-sm hover:shadow-tactile transition-all hover:-translate-y-1 cursor-default">
              <FileText className="w-5 h-5 text-[#6b8e7f] shrink-0 mt-0.5" />
              <div>
                <div className="font-extrabold text-[#4a5d52] text-sm mb-1">敷衍語意模版</div>
                <div className="text-xs text-[#6b8e7f] leading-relaxed">重複出現「服務很好，餐點好吃，推薦！」等缺乏具體餐點細節的空泛語句。</div>
              </div>
            </div>
            <div className="flex items-start gap-4 bg-[#f5f1e8] hover:bg-white rounded-2xl p-5 border-2 border-[#4a5d52] shadow-tactile-sm hover:shadow-tactile transition-all hover:-translate-y-1 cursor-default">
              <Sparkles className="w-5 h-5 text-[#e8c547] shrink-0 mt-0.5" />
              <div>
                <div className="font-extrabold text-[#4a5d52] text-sm mb-1">打卡送小菜/優惠</div>
                <div className="text-xs text-[#6b8e7f] leading-relaxed">提及「打卡送飲料」、「好評送甜點」等，以利益交換引導非自發性高分。</div>
              </div>
            </div>
            <div className="flex items-start gap-4 bg-[#f5f1e8] hover:bg-white rounded-2xl p-5 border-2 border-[#4a5d52] shadow-tactile-sm hover:shadow-tactile transition-all hover:-translate-y-1 cursor-default">
              <AlertTriangle className="w-5 h-5 text-[#e8c547] shrink-0 mt-0.5" />
              <div>
                <div className="font-extrabold text-[#4a5d52] text-sm mb-1">評分與內文割裂</div>
                <div className="text-xs text-[#6b8e7f] leading-relaxed">給予 5 星滿分，但文字卻包含「很難吃、态度差、等很久」等負向語意反饋。</div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* CTA Section */}
        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.5 }}
          className="text-center bg-[#6b8e7f] text-white rounded-[32px] p-12 shadow-tactile border-4 border-[#4a5d52] relative overflow-hidden"
        >
          <div className="absolute right-0 top-0 translate-x-12 -translate-y-12 w-48 h-48 bg-white/10 rounded-full blur-2xl"></div>
          <h2 className="text-3xl font-black mb-4 font-display tracking-wide">準備好辨別地圖上的真假好評了嗎？</h2>
          <p className="text-sm md:text-base mb-8 opacity-95 max-w-lg mx-auto leading-relaxed font-bold">
            系統支援一次輸入最多 3 間同類型店家進行「水軍過濾」與「真實口碑對比」，助您找到最實在的聚餐去處。
          </p>
          <motion.button
            onClick={() => navigate('/analyzer')}
            whileHover={{ y: -4 }}
            whileTap={{ y: 0, boxShadow: '0px 0px 0px 0px var(--color-primary)' }}
            className="bg-[#e8c547] text-[#4a5d52] px-8 py-3.5 rounded-full text-base font-black shadow-[4px_4px_0px_0px_#4a5d52] hover:shadow-[6px_6px_0px_0px_#4a5d52] transition-all border-3 border-[#4a5d52] flex items-center gap-2 mx-auto cursor-pointer font-display tracking-wider"
          >
            立即啟動對比
            <ArrowRight className="w-5 h-5 stroke-[3]" />
          </motion.button>
        </motion.div>

        {/* Footnote */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8 }}
          className="mt-12 text-center text-[10px] text-[#6b8e7f]/80 leading-relaxed max-w-3xl mx-auto"
        >
          <p>免責聲明：本平台基於自然語言處理 (NLP) 演算法及時間序列 analysis 對 Google Maps 評論數據集進行行為模式判定。分析報告旨在揭露異常資料及提高消費市場透明度，所提供評分結果僅供使用者個人消費決策之參考，不代表本平台對特定商家之衛生、品質或服務水準之保證，亦不對因此產生之任何消費爭議承擔法律責任。</p>
        </motion.div>
      </div>
    </div>
  );
}
