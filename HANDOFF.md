# HANDOFF：期末版本 → 現在的所有改動

> 對象：熟悉期末版本（6/8，`815eb9e`）的組員
> 截止：2026-08-06，tag `pre-migration-baseline`（`5110afb`）
> 最新 commit：`4d4ab40`

---

## 一句話總結

後端從「前端直接呼叫 Gemini API」重構成「Flask 統一處理爬蟲＋審計」，爬蟲主路徑換成 Apify 雲端服務，加了完整的測試和離線評估工具，修掉一個會讓星等偏低的公式 bug，並規劃了下一版的 AI 總結與問答功能。

---

## 1. Gemini 審計從前端移到後端

**期末版本怎麼做的：** 使用者在前端輸入自己的 Gemini API key，Results.tsx 直接從瀏覽器呼叫 `generativelanguage.googleapis.com`。

**現在怎麼做的：** 前端 `POST /api/audit`，後端 `server.py` 用伺服器端的 `GEMINI_API_KEY` 呼叫 Gemini。使用者不再需要提供自己的 API key。

**為什麼改：** API key 放前端有安全風險（使用者可以從 DevTools 看到），而且每個使用者都要自己申請 key 門檻太高。

**新增的檔案：**
- `review_scraper/gemini_client.py` — 分批（~40 則/批）呼叫 Gemini，解析 JSON 回應
- `review_scraper/prompt_builder.py` — 組裝 Stage 2 prompt，注入 `daysElapsed`、`isSpikePeriod` 等時間特徵

**受影響的檔案：**
- `server.py` — 新增 `POST /api/audit` 路由
- `Results.tsx` — 改成 `fetch('/api/audit')`，不再直接呼叫 Gemini

---

## 2. 爬蟲主路徑換成 Apify

**期末版本怎麼做的：** 只有本地 Playwright 爬蟲，需要裝瀏覽器，速度慢。

**現在怎麼做的：** 主路徑是 Apify 雲端爬蟲（`compass/Google-Maps-Reviews-Scraper`），Playwright 降級為可選的 fallback（預設關閉，需設 `ENABLE_PLAYWRIGHT_FALLBACK=true`）。

**為什麼改：** Playwright 在 serverless 平台跑不動，而且 Google 反爬越來越嚴格。Apify 是付費服務但穩定。

**新增的檔案：**
- `review_scraper/apify_scraper.py` — Apify 爬蟲封裝
- `review_scraper/normalize.py` — 統一 Apify/Playwright 回傳的不同欄位格式
- `review_scraper/cache_store.py` — 爬取結果快取，避免重複呼叫 Apify 燒錢

**環境變數（`.env`）：**
- `APIFY_TOKEN` — Apify API token（必填）
- `GEMINI_API_KEY` — Gemini API key（必填，從前端移到後端）
- `ENABLE_PLAYWRIGHT_FALLBACK` — 是否啟用 Playwright fallback（預設 `false`）

---

## 3. Gemini prompt 大幅改寫

**改了什麼：**
- 新增 5 個輸入特徵欄位給 Gemini 參考：`maxSimilarity`、`similarCount`、`hotTermCount`、`hotTermMaxRatio`、`nearbyLongReviewCount`
- 新增「高細節模板洗評」規則：描述再細緻，只要結構相似度高 + 暴增期 + 熱門詞組集中，一律判洗評
- 新增「短評但真實」的正面範例（範例 D），防止 Gemini 把所有短評都判成洗評
- 強制 `reasoningPath` 排在 `isWashed` 前面，要求先推理再下結論

**為什麼改：** 期末版本的 prompt 抓不到「專業代寫的行銷長評」——這些評論描述很細緻但全店都長一樣。加入結構性訊號後 Gemini 能交叉比對。

---

## 4. 修掉 trustPenalty 重複懲罰 bug

**期末版本的問題：** `filteredRating` 計算時，洗評先透過 weight 公式壓低星等貢獻，然後 `trustPenalty` 又按洗評比例額外扣最多 2 星。同一批洗評被懲罰了兩次。

**實際影響有多大：** 一家 4.5 星、30% 洗評的店，weight 過濾降 0.4 星（合理），trustPenalty 再扣 1.2 星（不合理），最終被打到 2.9 星。trustPenalty 佔了總降幅的 75%。

**現在怎麼做的：** `filteredRating = sum(stars × weight) / sum(weight)`，純加權平均，沒有額外扣減。Trust Score 保留在 UI 顯示（作為「這家店評論生態多可疑」的獨立指標），但不再動星等。

**受影響的檔案：** `auditEngine.ts`（移除 trustPenalty 計算）、`auditEngine.test.ts`（更新預期值 + 新增回歸測試）、`TRUE_RATING_LOGIC.md`（記錄移除理由）

---

## 5. 信心指數公式：文件對齊實際程式碼

**期末版本的情況：** `TRUE_RATING_LOGIC.md` 寫的是線性公式（50%–99% 範圍），但 code 用的是冪次曲線（`agreement^1.5 × 100`，0%–100% 範圍）。文件跟程式碼不一致。

**決定：** 保留冪次曲線（它區分度更好，而且 UI 的「< 50% 顯示琥珀色疑似洗評」依賴 0–100% 範圍），更新文件對齊程式碼。

---

## 6. Stage 2 抽樣模式開關

**期末版本怎麼做的：** 所有模糊 5 星評論全部送 Gemini，沒有上限。

**現在怎麼做的：** 用 `VITE_AUDIT_MODE` 環境變數控制：
- `production`（預設）：最多 15 則，按 `isSpikePeriod` 分層等距取樣
- `evaluate`：全送，不設上限

**為什麼改：** 生產環境要控 Gemini API 成本；但離線評估需要全覆蓋數字才準確。

---

## 7. 加了測試和離線評估工具

期末版本沒有任何自動化測試。現在有：

**前端測試（vitest）：**
- `src/app/utils/auditEngine.test.ts` — 20 個測試，涵蓋加權公式、Stage 1 規則、相似度訊號等
- 跑法：`npm test`

**後端測試（pytest）：**
- `tests/test_*.py` — 涵蓋 normalize、Apify scraper、Gemini client、prompt builder、audit API
- 跑法：`cd review_scraper && python -m pytest tests/`

**離線評估腳本：**
- `evaluate.py` — 用 18 家標註店跑 Stage 1 精準度/召回率/F1
- `evaluate_v2.py` — 網格搜尋最佳門檻 + 產出 Stage 2 LLM 抽樣輸入
- `sample_fp.py` — 抽樣 false positive 店家，產出 Gemini prompt 文字檔
- `check_data.py` — 檢查 CSV 欄位一致性

---

## 8. 規劃中的新功能（已起草 prompt，尚未接線）

- **單店 AI 總結**（`/api/summarize`，`mode: "single"`）：從真實評論產出「避雷提示」+「推薦品項」，每條附出處評論 id
- **店家頁即時問答**（`/api/summarize`，`mode: "qa"`）：使用者問問題，後端用真實評論回答，每店每 session 限 3 題
- Prompt 初稿在 `review_scraper/summarize_prompt.txt` 和 `review_scraper/qa_prompt.txt`
- 這些功能排在 B1 引擎遷移完成後才做

---

## 9. 刪掉的東西

| 刪了什麼 | 為什麼 |
|---------|--------|
| `review_scraper/vite_middleware.js` | 舊的 Vite dev middleware 實作，已被 Flask + Vite proxy 取代 |
| Ollama 本地模型支援 | Gemini 是唯一的 Stage 2 路徑，Ollama 選項移除 |
| 前端 Gemini API key 輸入框 | API key 改放後端 `.env` |

---

## 10. 重要的 tag

| Tag | Commit | 日期 | 用途 |
|-----|--------|------|------|
| `pre-migration-baseline` | `5110afb` | 2026-08-06 | B1 遷移後 TS/Python 輸出一致性驗證的凍結點，也是所有評估對照的基準版本 |

---

## 要跑起來需要做什麼

1. 複製 `.env.example` 為 `.env`，填入 `GEMINI_API_KEY` 和 `APIFY_TOKEN`
2. `npm install`
3. `./run.sh`（或分開跑 `npm run dev:scraper` + `npm run dev`）

跟期末版本比，主要就是多了兩個必填的環境變數。
