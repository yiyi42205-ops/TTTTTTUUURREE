import { useState, useEffect } from 'react';
import { Key, Check, AlertCircle, Eye, EyeOff, Save, Trash2, ChevronDown } from 'lucide-react';
import { motion } from 'motion/react';

type ProviderType = 'gemini' | 'deepseek' | 'openai_compatible';

interface ProviderOption {
  id: ProviderType;
  label: string;
  description: string;
}

const PROVIDERS: ProviderOption[] = [
  { id: 'gemini', label: 'Gemini（預設）', description: '免費的 Gemini 2.5 Flash Lite，無需設定即可使用' },
  { id: 'deepseek', label: 'DeepSeek', description: 'DeepSeek Chat，需自備 API Key' },
  { id: 'openai_compatible', label: '自訂模型', description: '任何 OpenAI 相容的 API（Groq、Mistral、Together、OpenRouter、Ollama 等）' },
];

const STORAGE_KEYS = {
  provider: 'truerating_llm_provider',
  geminiKey: 'truerating_gemini_api_key',
  deepseekKey: 'truerating_deepseek_api_key',
  customKey: 'truerating_custom_api_key',
  customBaseUrl: 'truerating_custom_base_url',
  customModel: 'truerating_custom_model_name',
};

export function Settings() {
  const [provider, setProvider] = useState<ProviderType>('gemini');
  const [geminiKey, setGeminiKey] = useState('');
  const [deepseekKey, setDeepseekKey] = useState('');
  const [customKey, setCustomKey] = useState('');
  const [customBaseUrl, setCustomBaseUrl] = useState('');
  const [customModel, setCustomModel] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  useEffect(() => {
    setProvider((sessionStorage.getItem(STORAGE_KEYS.provider) as ProviderType) || 'gemini');
    setGeminiKey(sessionStorage.getItem(STORAGE_KEYS.geminiKey) || '');
    setDeepseekKey(sessionStorage.getItem(STORAGE_KEYS.deepseekKey) || '');
    setCustomKey(sessionStorage.getItem(STORAGE_KEYS.customKey) || '');
    setCustomBaseUrl(sessionStorage.getItem(STORAGE_KEYS.customBaseUrl) || '');
    setCustomModel(sessionStorage.getItem(STORAGE_KEYS.customModel) || '');
  }, []);

  const handleSave = () => {
    setStatus('idle');

    // Validate provider-specific fields
    if (provider === 'gemini') {
      const trimmed = geminiKey.trim();
      if (trimmed && !trimmed.startsWith('AIzaSy')) {
        setStatus('error');
        setMessage('Gemini 金鑰格式不正確，通常以 "AIzaSy" 開頭。');
        return;
      }
      sessionStorage.setItem(STORAGE_KEYS.geminiKey, trimmed);
    } else if (provider === 'deepseek') {
      const trimmed = deepseekKey.trim();
      if (!trimmed) {
        setStatus('error');
        setMessage('請輸入 DeepSeek API Key。');
        return;
      }
      if (!trimmed.startsWith('sk-')) {
        setStatus('error');
        setMessage('DeepSeek API Key 格式不正確，通常以 "sk-" 開頭。');
        return;
      }
      sessionStorage.setItem(STORAGE_KEYS.deepseekKey, trimmed);
    } else if (provider === 'openai_compatible') {
      if (!customKey.trim() || !customBaseUrl.trim() || !customModel.trim()) {
        setStatus('error');
        setMessage('自訂模型需要填寫 API Key、Base URL 和模型名稱。');
        return;
      }
      sessionStorage.setItem(STORAGE_KEYS.customKey, customKey.trim());
      sessionStorage.setItem(STORAGE_KEYS.customBaseUrl, customBaseUrl.trim());
      sessionStorage.setItem(STORAGE_KEYS.customModel, customModel.trim());
    }

    sessionStorage.setItem(STORAGE_KEYS.provider, provider);
    setStatus('success');
    setMessage('設定已儲存！金鑰僅保存於當前 Session，關閉分頁即清除。');
  };

  const handleClear = () => {
    Object.values(STORAGE_KEYS).forEach(k => sessionStorage.removeItem(k));
    setProvider('gemini');
    setGeminiKey('');
    setDeepseekKey('');
    setCustomKey('');
    setCustomBaseUrl('');
    setCustomModel('');
    setStatus('success');
    setMessage('已清除所有設定，將使用預設的免費 Gemini 模型。');
  };

  return (
    <div className="flex-1 overflow-y-auto bg-background p-4 md:p-8 pb-24">
      <div className="max-w-md mx-auto">
        {/* Header */}
        <div className="mb-8 text-center md:text-left">
          <h1 className="text-2xl font-semibold text-ink tracking-[-0.6px] mb-2">
            AI 模型設定
          </h1>
          <p className="text-sm text-ink-subtle leading-relaxed">
            選擇語意分析使用的 AI 模型。預設免費，也可自備金鑰使用其他模型。
          </p>
        </div>

        {/* Provider Selector */}
        <div className="bg-surface-1 rounded-xl p-6 border border-hairline mb-4">
          <div className="flex items-center gap-2.5 mb-4 text-ink">
            <Key className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold tracking-[-0.4px]">AI 模型</h2>
          </div>

          <div className="relative mb-5">
            <select
              value={provider}
              onChange={(e) => { setProvider(e.target.value as ProviderType); setStatus('idle'); }}
              className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink appearance-none cursor-pointer focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
            >
              {PROVIDERS.map(p => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-subtle pointer-events-none" />
          </div>

          <p className="text-xs text-ink-tertiary mb-5">
            {PROVIDERS.find(p => p.id === provider)?.description}
          </p>

          {/* Provider-specific fields */}
          <div className="space-y-4">
            {provider === 'gemini' && (
              <>
                <label className="block text-xs font-medium text-ink-subtle uppercase tracking-wider">
                  Gemini API Key（選填，留空使用免費預設）
                </label>
                <div className="relative">
                  <input
                    type={showKey ? 'text' : 'password'}
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                    placeholder="AIzaSy..."
                    className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20 pr-12 placeholder-ink-tertiary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle cursor-pointer"
                  >
                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </>
            )}

            {provider === 'deepseek' && (
              <>
                <label className="block text-xs font-medium text-ink-subtle uppercase tracking-wider">
                  DeepSeek API Key
                </label>
                <div className="relative">
                  <input
                    type={showKey ? 'text' : 'password'}
                    value={deepseekKey}
                    onChange={(e) => setDeepseekKey(e.target.value)}
                    placeholder="sk-..."
                    className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20 pr-12 placeholder-ink-tertiary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle cursor-pointer"
                  >
                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </>
            )}

            {provider === 'openai_compatible' && (
              <>
                <label className="block text-xs font-medium text-ink-subtle uppercase tracking-wider">
                  API Key
                </label>
                <div className="relative">
                  <input
                    type={showKey ? 'text' : 'password'}
                    value={customKey}
                    onChange={(e) => setCustomKey(e.target.value)}
                    placeholder="你的 API Key"
                    className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20 pr-12 placeholder-ink-tertiary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink-subtle cursor-pointer"
                  >
                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>

                <label className="block text-xs font-medium text-ink-subtle uppercase tracking-wider">
                  Base URL
                </label>
                <input
                  type="text"
                  value={customBaseUrl}
                  onChange={(e) => setCustomBaseUrl(e.target.value)}
                  placeholder="例如 https://api.groq.com/openai/v1"
                  className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20 placeholder-ink-tertiary"
                />

                <label className="block text-xs font-medium text-ink-subtle uppercase tracking-wider">
                  模型名稱
                </label>
                <input
                  type="text"
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="例如 llama-3.3-70b-versatile"
                  className="w-full bg-surface-2 border border-hairline rounded-lg px-4 py-3 text-sm text-ink focus:outline-hidden focus:border-primary/50 focus:ring-1 focus:ring-primary/20 placeholder-ink-tertiary"
                />
              </>
            )}

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
              <button
                onClick={handleClear}
                className="bg-surface-2 text-[var(--semantic-danger)] border border-hairline p-3 rounded-lg hover:bg-[var(--semantic-danger)]/10 transition-all flex items-center justify-center cursor-pointer"
                title="清除所有設定"
              >
                <Trash2 className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>

        {/* Common Providers Reference */}
        <div className="bg-surface-1 rounded-xl p-6 border border-hairline mb-4">
          <h3 className="text-sm font-semibold text-ink mb-3">常用 OpenAI 相容服務</h3>
          <div className="space-y-2 text-xs text-ink-subtle">
            <div className="flex justify-between bg-surface-2 rounded p-2.5">
              <span className="font-medium text-ink">Groq</span>
              <code className="text-ink-tertiary">https://api.groq.com/openai/v1</code>
            </div>
            <div className="flex justify-between bg-surface-2 rounded p-2.5">
              <span className="font-medium text-ink">Together</span>
              <code className="text-ink-tertiary">https://api.together.xyz/v1</code>
            </div>
            <div className="flex justify-between bg-surface-2 rounded p-2.5">
              <span className="font-medium text-ink">OpenRouter</span>
              <code className="text-ink-tertiary">https://openrouter.ai/api/v1</code>
            </div>
            <div className="flex justify-between bg-surface-2 rounded p-2.5">
              <span className="font-medium text-ink">Mistral</span>
              <code className="text-ink-tertiary">https://api.mistral.ai/v1</code>
            </div>
            <div className="flex justify-between bg-surface-2 rounded p-2.5">
              <span className="font-medium text-ink">Ollama（本機）</span>
              <code className="text-ink-tertiary">http://localhost:11434/v1</code>
            </div>
          </div>
        </div>

        {/* Help Card */}
        <div className="bg-primary/5 rounded-xl p-6 border border-primary/15">
          <h3 className="text-ink font-medium text-sm mb-2.5 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-primary" />
            如何取得免費 Gemini API Key？
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
            <li>點選「Create API Key」</li>
            <li>複製產生的金鑰（開頭為 AIzaSy），並貼入上方儲存</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
