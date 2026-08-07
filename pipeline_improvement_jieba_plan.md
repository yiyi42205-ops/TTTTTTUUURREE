# 🚀 Pipeline 改善計畫：引進 Jieba (結巴) 詞性標註重構 `low_info` 低資訊量審計機制

> **定位**：技術架構改善計畫 (RFC / Technical Proposal)  
> **狀態**：規劃中 (Draft) —— 本文件僅儲存於本地，不 Push 至 GitHub 儲存庫。

---

## 1. 現狀問題與痛點回顧

在 TrueRating 階段一（Stage 1）啟發式規則中，`low_info`（低資訊量評論）的判定過去採用字詞 Match（`EMPTY_WORDS.has()`）：
* **問題**：`"好吃"` 觸發 `low_info`，但 `"蛤蜊好吃"` / `"牛肉讚"` 無法觸發。硬維護名詞字典（如寫死 `['牛肉', '蛤蜊', '拉麵']`）維護成本高且無法覆蓋無限的自然語言組合。

---

## 2. 核心技術方案：基於 Jieba POS (詞性標註) 的語法結構判定

藉由引進 `jieba.posseg`（結巴詞性標註），我們不需要維護龐大的「餐廳食材與景點名詞庫」，改為對評論文字進行**詞性與語法結構解析 (Part-of-Speech Structure Analysis)**。

### 2.1 詞性標註規則 (POS Rules)

1. **實體詞彙與動詞 (Anchored Tokens)**：
   - 名詞標籤 `n*` (`n`, `nr`, `ns`, `nt`, `nz`) —— 例：`蛤蜊`、`牛肉`、`醬汁`、`環境`、`服務`。
   - 動詞標籤 `v*` (`v`, `vd`, `vn`) —— 例：`排隊`、`等待`、`補貨`。
2. **修飾詞與評價詞 (Unanchored Modifiers)**：
   - 形容詞標籤 `a*` (`a`, `ad`) —— 例：`好吃`、`讚`、`棒`、`甜`。
   - 副詞標籤 `d*` (`d`) —— 例：`超`、`很`、`極`、`不`。

### 2.2 判定邏輯決策樹 (Decision Tree)

```
[評論文字] 
    │
    ▼
1. 標點符號與 Emoji 清理
    │
    ▼
2. 否定詞與負評短路保護 (Check '不', '沒', '無', '普普', '雷') ──► 若存在 ──► 非 low_info (保留為 Clean)
    │
    ▼
3. Jieba 詞性切分 (jieba.posseg.cut)
    │
    ▼
4. 統計名詞數 (count_N)、動詞數 (count_V)、形容詞/副詞數 (count_A_D)
    │
    ├── A. (字數 <= 8) AND (count_N == 0) AND (count_V == 0) AND (count_A_D > 0)
    │      └──► 判定為 low_info = True (純形容詞/副詞空泛讚賞)
    │
    └── B. 包含名詞 (count_N > 0) OR 包含動詞 (count_V > 0) OR 字數 > 8
           └──► 判定為 low_info = False (具備實體與具體描寫)
```

---

## 3. 案例判定推演矩陣 (Verification Matrix)

| 評論文字 | Jieba POS 切分結果 | 名詞/動詞數 | 判決結果 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `"好吃"` | `[('好吃', 'a')]` | N=0, V=0 | **`low_info = True`** | 純形容詞，無實體 |
| `"超讚"` | `[('超', 'd'), ('讚', 'a')]` | N=0, V=0 | **`low_info = True`** | 副詞+形容詞，無實體 |
| `"蛤蜊好吃"` | `[('蛤蜊', 'n'), ('好吃', 'a')]` | **N=1** | **`low_info = False`** | 包含名詞實體「蛤蜊」 |
| `"牛肉讚"` | `[('牛肉', 'n'), ('讚', 'a')]` | **N=1** | **`low_info = False`** | 包含名詞實體「牛肉」 |
| `"醬偏甜"` | `[('醬', 'n'), ('偏', 'd'), ('甜', 'a')]` | **N=1** | **`low_info = False`** | 高密度短評，保護成功 |
| `"牛肉不好吃"` | 短路保護命中（`"不"`） | - | **`low_info = False`** | 負面批判，絕對不誤殺 |
| `"排骨飯醬汁很入味"` | `[('排骨飯', 'n'), ('醬汁', 'n'), ...]` | **N=2** | **`low_info = False`** | 具體描述，順利通過 |

---

## 4. 影響範圍與檔案修改計畫

1. **[NEW] `review_scraper/pos_classifier.py`**
   - 封裝 `jieba.posseg` 邏輯與自訂補充字典（例如加入 `"CP值"` 為名詞）。
2. **[MODIFY] `review_scraper/requirements.txt`**
   - 新增 `jieba>=0.42.1`（純 Python 實現，無 C 編譯依賴，檔案約 20MB）。
3. **[MODIFY] `review_scraper/server.py`**
   - 接入 `/api/audit` API。
4. **[MODIFY] `evaluate.py` / `evaluate_v2.py`**
   - 直連 `pos_classifier.py` 跑 18 家標註資料集，對照 `pre-migration-baseline` (`5110afb`) 的 F1 分數。
5. **[NEW] `review_scraper/tests/test_pos_classifier.py`**
   - 新增完整的單元測試對照集。

---

## 5. 驗收標準 (DoD)

- [ ] `pytest tests/test_pos_classifier.py` 100% 通過。
- [ ] 執行 `evaluate.py` 確定 18 家店整體 F1 分數不低於基準 commit (`5110afb`)。
- [ ] 確定程式碼只保留在本地，未 push 至 GitHub 遠端儲存庫。
