#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
資料品質診斷:檢查所有 CSV 的欄位 + Time 格式是否一致。

用法:
  python3 eval/check_data.py restaurant_data
"""
import csv
import sys
from pathlib import Path


def check_file(csv_path):
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        rows = list(reader)

    issues = []

    # 檢查 1:欄位完整性
    expected = {'Username', 'Stars', 'Time', 'RawTime', 'Text'}
    missing = expected - set(cols or [])
    if missing:
        issues.append(f"缺欄位 {missing}")

    # 檢查 2:Time 格式
    if not rows:
        issues.append("空資料")
    else:
        sample_time = rows[0].get('Time', '')
        # 標準格式應該是 YYYY-MM-DD
        if not (len(sample_time) == 10 and sample_time[4] == '-' and sample_time[7] == '-'):
            issues.append(f"Time 格式異常 (範例:'{sample_time}')")

    # 檢查 3:行數
    if rows and len(rows) < 10:
        issues.append(f"評論數過少 ({len(rows)} 則)")

    return {
        'path': csv_path,
        'cols': cols,
        'rows': len(rows),
        'sample_time': rows[0].get('Time', '') if rows else None,
        'issues': issues,
    }


def main():
    if len(sys.argv) < 2:
        print('用法: python3 eval/check_data.py <restaurant_data 路徑>')
        sys.exit(1)

    base = Path(sys.argv[1])
    bad = []
    good = []

    for csv_file in sorted(base.rglob('*.csv')):
        info = check_file(csv_file)
        if info['issues']:
            bad.append(info)
        else:
            good.append(info)

    print(f"\n{'=' * 70}")
    print(f"資料品質檢查:共 {len(bad) + len(good)} 家店")
    print('=' * 70)

    print(f"\n✅ 格式正常 ({len(good)} 家):")
    for info in good:
        print(f"  {info['path'].parent.name}/{info['path'].name}  "
              f"({info['rows']} 則,Time={info['sample_time']})")

    print(f"\n⚠️  有問題 ({len(bad)} 家):")
    for info in bad:
        print(f"  {info['path'].parent.name}/{info['path'].name}")
        for issue in info['issues']:
            print(f"    └─ {issue}")
        print(f"    └─ 欄位:{info['cols']}")
        print(f"    └─ 行數:{info['rows']}")


if __name__ == '__main__':
    main()
