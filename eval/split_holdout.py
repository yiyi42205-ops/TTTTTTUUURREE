#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
將 restaurant_data/ 的店家切分為 train / holdout。

切分原則:
  - 6 家 holdout（約 ~18% of ~33 家）
  - 平衡: 新舊店、有洗/沒洗、各類別都分散

用法:
  python3 eval/split_holdout.py

只輸出名單，不移動檔案。holdout 標記存入 eval/holdout.json。
"""
import json
import random
from collections import defaultdict
from pathlib import Path

HOLDOUT_COUNT = 6
SEED = 42  # 固定 seed 可重現

def main():
    base = Path(__file__).resolve().parent.parent / 'restaurant_data'
    stores = []

    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir() or '__' not in subdir.name:
            continue
        category, label = subdir.name.split('__', 1)
        for csv_file in sorted(subdir.glob('*.csv')):
            stores.append({
                'name': csv_file.stem,
                'category': category,
                'label': label,
                'path': str(csv_file.relative_to(base)),
            })

    print(f'總店家數: {len(stores)}')
    print()

    # Group by (category, label) for stratified sampling
    groups = defaultdict(list)
    for s in stores:
        groups[(s['category'], s['label'])].append(s)

    print('各組分佈:')
    for (cat, lbl), members in sorted(groups.items()):
        print(f'  {cat}__{lbl}: {len(members)} 家')
    print()

    # Stratified holdout: pick proportionally from each group
    random.seed(SEED)
    holdout = []
    train = []

    # Calculate how many to pick from each group
    total = len(stores)
    remaining_holdout = HOLDOUT_COUNT

    group_keys = sorted(groups.keys())
    picks_per_group = {}

    for key in group_keys:
        proportion = len(groups[key]) / total
        pick = max(1, round(proportion * HOLDOUT_COUNT))
        picks_per_group[key] = min(pick, len(groups[key]) - 1)  # Keep at least 1 in train

    # Adjust to hit exact HOLDOUT_COUNT
    while sum(picks_per_group.values()) > HOLDOUT_COUNT:
        # Remove from largest group
        largest = max(picks_per_group, key=lambda k: picks_per_group[k])
        picks_per_group[largest] -= 1
    while sum(picks_per_group.values()) < HOLDOUT_COUNT:
        # Add to largest group with room
        for key in sorted(group_keys, key=lambda k: len(groups[k]), reverse=True):
            if picks_per_group[key] < len(groups[key]) - 1:
                picks_per_group[key] += 1
                break

    for key in group_keys:
        members = groups[key][:]
        random.shuffle(members)
        n = picks_per_group.get(key, 0)
        holdout.extend(members[:n])
        train.extend(members[n:])

    # Sort for readability
    holdout.sort(key=lambda s: (s['category'], s['label'], s['name']))
    train.sort(key=lambda s: (s['category'], s['label'], s['name']))

    print(f'Holdout ({len(holdout)} 家):')
    for s in holdout:
        print(f'  {s["category"]}__{s["label"]}/{s["name"]}')

    print(f'\nTrain ({len(train)} 家):')
    for s in train:
        print(f'  {s["category"]}__{s["label"]}/{s["name"]}')

    # Verify balance
    print('\n── 平衡檢查 ──')
    for split_name, split in [('holdout', holdout), ('train', train)]:
        cats = defaultdict(int)
        labels = defaultdict(int)
        for s in split:
            cats[s['category']] += 1
            labels[s['label']] += 1
        print(f'  {split_name}: 類別={dict(cats)}, 判定={dict(labels)}')

    # Save
    out_path = Path(__file__).resolve().parent / 'holdout.json'
    out_path.write_text(json.dumps({
        'holdout': [s['name'] for s in holdout],
        'train': [s['name'] for s in train],
        'holdout_detail': holdout,
        'train_detail': train,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已儲存: {out_path}')


if __name__ == '__main__':
    main()
