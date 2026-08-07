import { useState, useEffect } from 'react';
import { Key, Check, AlertCircle, Eye, EyeOff, Save, Trash2 } from 'lucide-react';
import { motion } from 'motion/react';

export function Settings() {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

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
      setMessage('設定已清除，系統將使用預設的伺服器金鑰。');
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
    setMessage('已清除 Session 金鑰，將回到伺服器託管金鑰。');
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#f5f1e8] p-4 md:p-8 pb-24">
      <div className="max-w-md mx-auto">
        {/* Header */}
        <div className="mb-8 text-center md:text-left">
          <h1 className="text-3xl font-black text-[#4a5d52] font-display tracking-tight mb-2">
            系統設定
          </h1>
          <p className="text-sm text-[#6b8e7f] font-medium leading-relaxed">
            配置您的個人 API 金鑰，實現無限制免費審計。
          </p>
        </div>

        {/* Form Card */}
        <div className="bg-white rounded-3xl p-6 border-3 border-[#4a5d52] shadow-tactile mb-6">
          <div className="flex items-center gap-2.5 mb-5 text-[#4a5d52]">
            <Key className="w-5 h-5 stroke-[2.5]" />
            <h2 className="text-lg font-black font-display">Gemini API Key 設定</h2>
          </div>

          <p className="text-xs text-[#6b8e7f] font-bold leading-relaxed mb-6">
            疑騙真星 TrueRating 為免費開源軟體。為了防止公共 API 流量遭濫用，您可以填入自己的免費 Google Gemini API Key。您的金鑰會安全地保存在當前分頁的 Session 中，關閉分頁或重整過久即會清除，絕不上傳資料庫。
          </p>

          <div className="space-y-4">
            <label className="block text-xs font-black text-[#4a5d52] uppercase tracking-wider">
              您的 Gemini API 金鑰
            </label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="輸入您的 AIzaSy... 金鑰"
                className="w-full bg-[#f5f1e8] border-2 border-[#4a5d52] rounded-xl px-4 py-3 text-sm font-medium text-[#4a5d52] focus:outline-hidden pr-12 focus:ring-2 focus:ring-[#6b8e7f]/20"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-[#6b8e7f] hover:text-[#4a5d52] focus:outline-hidden"
              >
                {showKey ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
              </button>
            </div>

            {/* Status Alert */}
            {status !== 'idle' && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex items-start gap-2.5 p-3 rounded-xl border-2 text-xs font-bold ${
                  status === 'success'
                    ? 'bg-[#6b8e7f]/10 border-[#6b8e7f]/30 text-[#4a5d52]'
                    : 'bg-[#ef4444]/10 border-[#ef4444]/30 text-[#ef4444]'
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
                className="flex-1 bg-[#6b8e7f] text-white py-3 rounded-xl text-sm font-black border-2 border-[#4a5d52] shadow-[3px_3px_0px_0px_#4a5d52] active:translate-x-0.5 active:translate-y-0.5 active:shadow-[1px_1px_0px_0px_#4a5d52] transition-all flex items-center justify-center gap-2 cursor-pointer font-display"
              >
                <Save className="w-4 h-4" />
                儲存設定
              </button>
              {apiKey && (
                <button
                  onClick={handleClear}
                  className="bg-[#f5f1e8] text-[#ef4444] border-2 border-[#4a5d52] p-3 rounded-xl hover:bg-[#ef4444]/5 active:translate-x-0.5 active:translate-y-0.5 transition-all flex items-center justify-center cursor-pointer"
                  title="清除金鑰"
                >
                  <Trash2 className="w-5 h-5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Helpful Info Card */}
        <div className="bg-[#6b8e7f]/10 rounded-3xl p-6 border-2 border-[#6b8e7f]/30">
          <h3 className="text-[#4a5d52] font-black text-sm mb-2.5 flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            如何取得免費 API Key？
          </h3>
          <ol className="text-xs text-[#6b8e7f] font-bold space-y-2 list-decimal list-inside leading-relaxed">
            <li>
              前往{' '}
              <a
                href="https://aistudio.google.com/app/apikey"
                target="_blank"
                rel="noreferrer"
                className="text-[#6b8e7f] underline hover:text-[#4a5d52] font-black"
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
    </div>
  );
}
