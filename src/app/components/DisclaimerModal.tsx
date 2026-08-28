import { useState, useEffect } from 'react';

const STORAGE_KEY = 'truerating_disclaimer_accepted';

export function DisclaimerModal() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem(STORAGE_KEY)) {
      setShow(true);
    }
  }, []);

  if (!show) return null;

  const handleAccept = () => {
    localStorage.setItem(STORAGE_KEY, '1');
    setShow(false);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/40 px-4">
      <div className="bg-background border border-hairline-strong rounded max-w-md w-full p-6 shadow-lg">
        <h2 className="text-base font-semibold text-ink mb-3">使用須知</h2>

        <div className="text-sm text-ink-muted leading-relaxed space-y-3 mb-6">
          <p>
            本平台透過自然語言處理演算法分析 Google Maps 評論的結構特徵，
            協助消費者辨識可能受利益誘因影響的評價。
          </p>
          <p>
            分析結果<span className="font-medium text-ink">僅供參考</span>，不代表對商家品質的最終評價，
            亦不保證判定結果的絕對正確性。請結合自身判斷做出消費決策。
          </p>
          <p className="text-xs text-ink-tertiary">
            繼續使用即表示您已閱讀並理解上述說明。
          </p>
        </div>

        <button
          onClick={handleAccept}
          className="w-full bg-ink hover:bg-ink-muted text-background py-2.5 rounded text-sm font-medium transition-colors cursor-pointer"
        >
          我知道了
        </button>
      </div>
    </div>
  );
}
