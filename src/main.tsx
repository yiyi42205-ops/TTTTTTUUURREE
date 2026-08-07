import { createRoot } from "react-dom/client";
import App from "./app/App.tsx";
import "./styles/index.css";
import { registerSW } from 'virtual:pwa-register';

// Register service worker and handle updates automatically
const updateSW = registerSW({
  onNeedRefresh() {
    if (confirm('新版的 TrueRating 已經準備就緒！是否立即重載網頁以套用更新？')) {
      updateSW(true);
    }
  },
  onOfflineReady() {
    console.log('TrueRating 離線模式已就緒，可作為 PWA 離線使用。');
  },
});

createRoot(document.getElementById("root")!).render(<App />);
  