import { useState, useEffect } from 'react';
import { Key, Check, AlertCircle, Eye, EyeOff, Save, Trash2, BookOpen, HelpCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useOnboarding } from '../hooks/useOnboarding';
import { OnboardingModal } from '../components/OnboardingModal';

export function Settings() {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const { isOpen: isOnboardingOpen, dismissOnboarding, resetOnboarding } = useOnboarding();

  useEffect(() => {
    const savedKey = sessionStorage.getItem('truerating_gemini_api_key');
    if (savedKey) {
      setApiKey(savedKey);
    }
  }, []);

  const handleSave = () => {
    const trimmed = apiKey.trim();
    if (!trimmed) {
      sessionStorage.removeItem('truerating_gemini_api_key');
      setStatus('success');
      setMessage('設定已清除，系統將使用預設的免費 Gemini 2.5 Flash Lite 模型。');
      return;
    }

    if (!trimmed.startsWith('AIzaSy')) {
      setStatus('error');
      setMessage('金鑰格式似乎不正確，通常以 "AIzaSy" 開頭。');
      return;
    }

    sessionStorage.setItem('truerating_gemini_api_key', trimmed);
    setStatus('success');
    setMessage('金鑰已安全儲存於當前 Session！關閉分頁即會清除。');
  };

  const handleClear = () => {
    setApiKey('');
    sessionStorage.removeItem('truerating_gemini_api_key');
    setStatus('success');
    setMessage('已清除 Session 金鑰，將使用預設的免費模型。');
  };

  return (
    <div className="flex-1 overflow-y-auto bg-background p-4 md:p-8 pb-24">
      <div className="max-w-md mx-auto">
        {/* Header */}
        <div className="mb-8 text-center md:text-left">
          <h1 className="text-2xl font-semibold text-ink tracking-[-0.6px] mb-2">
            系統設定
          </h1>
          <p className="text-sm text-ink-subtle leading-relaxed">
            配置您的個人 API 金鑰，或使用預設的免費 Gemini 2.5 Flash Lite 模型。
          </p>
        </div>

        {/* Form Card */}
        <div className="bg-surface-1 rounded-xl p-6 border border-hairline mb-6">
          <div className="flex items-center gap-2.5 mb-5 text-ink">
            <Key className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold tracking-[-0.4px]">Gemini API Key</h2>
          </div>

          <p className="text-sm text-ink-subtle leading-relaxed mb-6">
            疑騙真星為免費開源軟體，預設使用免費的 Gemini 2.5 Flash Lite 模型。如需使用更高階模型或避免公共流量限制，您可以填入自己的 Google Gemini API Key。金鑰僅保存在當前分頁的 Session 中，關閉分頁即清除。
          </p>

          <div className="space-y-4">
            <label className="block text-xs font-medium text-ink-subtle uppercase tracking-wider">
              您的 Gemini API 金鑰
            </label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="輸入您的 AIzaSy... 金鑰"
                className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20 pr-12 placeholder-ink-tertiary transition-all"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle focus:outline-hidden cursor-pointer"
              >
                {showKey ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
              </button>
            </div>

            {/* Status Alert */}
            {status !== 'idle' && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex items-start gap-2.5 p-3 rounded-lg border text-sm ${
                  status === 'success'
                    ? 'bg-[var(--semantic-success)]/10 border-[var(--semantic-success)]/20 text-[var(--semantic-success)]'
                    : 'bg-[var(--semantic-danger)]/10 border-[var(--semantic-danger)]/20 text-[var(--semantic-danger)]'
                }`}
              >
                {status === 'success' ? (
                  <Check className="w-4 h-4 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                )}
                <span>{message}</span>
              </motion.div>
            )}

            <div className="flex gap-3 pt-2">
              <button
                onClick={handleSave}
                className="flex-1 bg-primary hover:bg-primary-hover text-white py-3 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2 cursor-pointer"
              >
                <Save className="w-4 h-4" />
                儲存設定
              </button>
              {apiKey && (
                <button
                  onClick={handleClear}
                  className="bg-surface-2 text-[var(--semantic-danger)] border border-hairline p-3 rounded-lg hover:bg-[var(--semantic-danger)]/10 transition-all flex items-center justify-center cursor-pointer"
                  title="清除金鑰"
                >
                  <Trash2 className="w-5 h-5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Tutorial Card */}
        <div className="bg-surface-1 rounded-xl p-6 border border-hairline mb-6">
          <div className="flex items-center gap-2.5 mb-4 text-ink">
            <BookOpen className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold tracking-[-0.4px]">使用教學</h2>
          </div>
          <p className="text-sm text-ink-subtle leading-relaxed mb-4">
            第一次使用嗎？或是忘記怎麼操作了？重新觀看 4 步驟的新手教程，快速上手疑騙真星的所有功能。
          </p>
          <motion.button
            onClick={resetOnboarding}
            whileTap={{ scale: 0.98 }}
            className="w-full flex items-center justify-center gap-2 bg-surface-2 hover:bg-surface-3 text-ink-muted border border-hairline py-2.5 rounded-lg text-sm font-medium transition-all cursor-pointer"
          >
            <HelpCircle className="w-4 h-4" />
            重新觀看新手教程
          </motion.button>
        </div>

        {/* Help Card */}
        <div className="bg-primary/5 rounded-xl p-6 border border-primary/15">
          <h3 className="text-ink font-medium text-sm mb-2.5 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-primary" />
            如何取得免費 API Key？
          </h3>
          <ol className="text-sm text-ink-subtle space-y-2 list-decimal list-inside leading-relaxed">
            <li>
              前往{' '}
              <a
                href="https://aistudio.google.com/app/apikey"
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:text-primary-hover underline"
              >
                Google AI Studio Key 申請頁
              </a>
            </li>
            <li>登入您的 Google 帳號</li>
            <li>點選「Create API Key」（建立 API 金鑰）</li>
            <li>複製產生的金鑰（開頭為 AIzaSy），並貼入此頁面儲存</li>
          </ol>
        </div>
      </div>

      {/* Onboarding modal triggered from Settings */}
      <AnimatePresence>
        {isOnboardingOpen && (
          <OnboardingModal onDismiss={dismissOnboarding} />
        )}
      </AnimatePresence>
    </div>
  );
}
