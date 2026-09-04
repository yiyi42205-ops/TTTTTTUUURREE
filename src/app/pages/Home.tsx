import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { motion, useInView } from 'motion/react';
import { Shield, ArrowRight, Search, Info, Star, FileText } from 'lucide-react';
import { useIsPWA } from '../hooks/useIsPWA';
import { TutorialModal } from '../components/TutorialModal';

/* ── animated counter ─────────────────────────────────── */
function Counter({ target, suffix = '' }: { target: number; suffix?: string }) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (!inView) return;
    const duration = 1400;
    const start = performance.now();
    function tick(now: number) {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 4);          // easeOutQuart
      setCount(Math.round(eased * target));
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }, [inView, target]);

  return <div ref={ref}>{count.toLocaleString()}{suffix}</div>;
}

/* ── motion variants ──────────────────────────────────── */
const stagger  = { hidden: {}, show: { transition: { staggerChildren: 0.12 } } };
const fadeUp   = { hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: 'easeOut' } } };
const fadeIn   = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { duration: 0.6 } } };

/* ── feature data ─────────────────────────────────────── */
const features = [
  { icon: Shield,   title: '結構健康度',  desc: '偵測時間爆發、利益交換、樣板短評' },
  { icon: Star,     title: '自然星等還原', desc: '信心加權過濾，還原自然口碑評分' },
  { icon: FileText, title: '語意透視',    desc: 'LLM 深度剖析每則評論真偽' },
];

/* ── page ─────────────────────────────────────────────── */
export function Home() {
  const navigate = useNavigate();
  const isPWA = useIsPWA();
  const [showTutorial, setShowTutorial] = useState(false);

  useEffect(() => {
    if (isPWA) navigate('/analyzer', { replace: true });
  }, [isPWA, navigate]);

  return (
    <div className="min-h-screen bg-background font-sans selection:bg-ink/10">
      {/* ── header ── */}
      <header className="sticky top-0 z-50 bg-background/80 backdrop-blur-sm border-b border-hairline px-4 md:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => navigate('/')}>
          <div className="bg-ink text-background w-8 h-8 rounded flex items-center justify-center">
            <Shield className="w-4.5 h-4.5" />
          </div>
          <span className="font-semibold text-base text-ink tracking-[-0.4px]">
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

      {/* ── hero ── */}
      <section className="container mx-auto px-4 pt-16 pb-16 md:pt-28 md:pb-24 max-w-3xl">
        <motion.div className="text-center" variants={stagger} initial="hidden" animate="show">
          <motion.h1
            variants={fadeUp}
            className="text-3xl md:text-[3.75rem] font-semibold text-ink tracking-[-1px] md:tracking-[-1.5px] leading-[1.15] md:leading-[1.08] mb-4 md:mb-5"
          >
            看穿灌水好評
            <br />
            <span className="text-ink-subtle">還原自然星等</span>
          </motion.h1>

          <motion.p variants={fadeUp} className="text-base md:text-lg text-ink-subtle mb-8 md:mb-12 max-w-sm mx-auto leading-relaxed">
            AI 驅動的 Google Maps 評論審計引擎
          </motion.p>

          <motion.div variants={fadeUp}>
            <button
              onClick={() => navigate('/analyzer')}
              className="group bg-ink hover:bg-ink-muted text-background px-8 py-3.5 md:px-10 md:py-4 rounded-lg text-base md:text-lg font-medium transition-all inline-flex items-center gap-3 cursor-pointer"
            >
              開始分析
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
          </motion.div>
        </motion.div>
      </section>

      {/* ── stats strip ── */}
      <motion.section
        className="border-y border-hairline bg-surface-1"
        variants={fadeIn}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: '-60px' }}
      >
        <div className="container mx-auto px-4 py-10 max-w-2xl flex justify-center">
          <div className="text-center">
            <div className="text-3xl md:text-4xl font-semibold text-ink tracking-[-1px]">
              <Counter target={1500} suffix="+" />
            </div>
            <div className="text-sm text-ink-subtle mt-1">家餐廳已收錄</div>
          </div>
        </div>
      </motion.section>

      {/* ── features ── */}
      <section className="container mx-auto px-4 py-14 md:py-24 max-w-3xl">
        <motion.div
          className="grid grid-cols-1 md:grid-cols-3 gap-5"
          variants={stagger}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: '-80px' }}
        >
          {features.map((f) => (
            <motion.div
              key={f.title}
              variants={fadeUp}
              whileHover={{ y: -4, transition: { duration: 0.2 } }}
              className="bg-surface-1 rounded-lg p-6 border border-hairline hover:border-hairline-strong hover:shadow-sm transition-[border-color,box-shadow] cursor-default"
            >
              <f.icon className="w-6 h-6 text-ink-subtle mb-4" />
              <h3 className="text-base font-semibold text-ink mb-2 tracking-[-0.3px]">{f.title}</h3>
              <p className="text-sm text-ink-subtle leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ── bottom CTA ── */}
      <section className="container mx-auto px-4 pb-16 md:pb-28 max-w-3xl">
        <motion.div
          className="text-center bg-surface-1 border border-hairline rounded-lg py-14 px-6"
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
        >
          <h2 className="text-2xl font-semibold text-ink tracking-[-0.6px] mb-6">
            別再被灌水評價騙了！
          </h2>
          <button
            onClick={() => navigate('/analyzer')}
            className="group bg-ink hover:bg-ink-muted text-background px-8 py-3.5 rounded-lg text-base font-medium transition-all inline-flex items-center gap-2.5 cursor-pointer"
          >
            立即開始
            <Search className="w-4.5 h-4.5 group-hover:scale-110 transition-transform" />
          </button>
        </motion.div>
      </section>
    </div>
  );
}
