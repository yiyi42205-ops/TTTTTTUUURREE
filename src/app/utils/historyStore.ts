import { ShopStats } from './auditEngine';

export interface HistoryEntry {
  storeName: string;
  timestamp: number;
  stats: ShopStats;
}

const STORAGE_KEY = 'truerating_audit_history';

export const historyStore = {
  getHistory(): HistoryEntry[] {
    try {
      const data = localStorage.getItem(STORAGE_KEY);
      if (!data) return [];
      const parsed = JSON.parse(data) as HistoryEntry[];
      return parsed.sort((a, b) => b.timestamp - a.timestamp);
    } catch (e) {
      console.error('Failed to load audit history from localStorage:', e);
      return [];
    }
  },

  saveHistory(stats: ShopStats): void {
    try {
      const history = this.getHistory();
      const existingIdx = history.findIndex(entry => entry.storeName === stats.storeName);
      
      const newEntry: HistoryEntry = {
        storeName: stats.storeName,
        timestamp: Date.now(),
        stats
      };

      if (existingIdx !== -1) {
        history[existingIdx] = newEntry;
      } else {
        history.push(newEntry);
      }

      localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    } catch (e) {
      console.error('Failed to save audit history to localStorage:', e);
    }
  },

  deleteHistory(storeName: string): void {
    try {
      const history = this.getHistory();
      const filtered = history.filter(entry => entry.storeName !== storeName);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
    } catch (e) {
      console.error('Failed to delete audit history entry:', e);
    }
  },

  clearHistory(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      console.error('Failed to clear audit history:', e);
    }
  }
};
