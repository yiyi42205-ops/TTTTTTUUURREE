import ramen_washed_1 from '../../../restaurant_data/餐廳__有洗/好呷拉麵X燒咖哩通化.csv?raw';
import ramen_washed_2 from '../../../restaurant_data/餐廳__有洗/好呷拉麵 甜品吃到飽(師大).csv?raw';
import ramen_washed_3 from '../../../restaurant_data/餐廳__有洗/麵屋長樂 台灣本店.csv?raw';

import ramen_clean_1 from '../../../restaurant_data/餐廳__沒洗/十二巷拉麵.csv?raw';
import ramen_clean_2 from '../../../restaurant_data/餐廳__沒洗/小高拉麵 公館.csv?raw';
import ramen_clean_3 from '../../../restaurant_data/餐廳__沒洗/隱家拉麵公館.csv?raw';

import bento_washed_1 from '../../../restaurant_data/餐廳__有洗/城市盒子寧波.csv?raw';
import bento_washed_2 from '../../../restaurant_data/餐廳__有洗/村民餐盒.csv?raw';
import bento_washed_3 from '../../../restaurant_data/餐廳__有洗/米泰豐.csv?raw';

import bento_clean_1 from '../../../restaurant_data/餐廳__沒洗/lulu lin 原型飯包金山店.csv?raw';
import bento_clean_2 from '../../../restaurant_data/餐廳__沒洗/餵way.csv?raw';
import bento_clean_3 from '../../../restaurant_data/餐廳__沒洗/龍城精緻快餐.csv?raw';

import drink_washed_1 from '../../../restaurant_data/飲料店__有洗/深夜茶飲.csv?raw';
import drink_washed_2 from '../../../restaurant_data/飲料店__有洗/發發公館牧場491.csv?raw';
import drink_washed_3 from '../../../restaurant_data/飲料店__有洗/茶沐-茶飲專賣店.csv?raw';

import drink_clean_1 from '../../../restaurant_data/飲料店__沒洗/可不可公館.csv?raw';
import drink_clean_2 from '../../../restaurant_data/飲料店__沒洗/清新師大.csv?raw';
import drink_clean_3 from '../../../restaurant_data/飲料店__沒洗/迷客夏延吉.csv?raw';

export interface Restaurant {
  id: string;
  name: string;
  category: 'restaurant' | 'drinks';
  categoryLabel: string;
  isWashed: boolean;
  csvContent: string;
}

export const RESTAURANTS_DATA: Restaurant[] = [
  // Restaurant (Ramen) - Washed
  {
    id: 'ramen_washed_1',
    name: '好假拉麵通化',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: true,
    csvContent: ramen_washed_1,
  },
  {
    id: 'ramen_washed_2',
    name: '好呷拉麵師大',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: true,
    csvContent: ramen_washed_2,
  },
  {
    id: 'ramen_washed_3',
    name: '麵屋長樂',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: true,
    csvContent: ramen_washed_3,
  },
  // Restaurant (Ramen) - Clean
  {
    id: 'ramen_clean_1',
    name: '十二巷拉麵',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: false,
    csvContent: ramen_clean_1,
  },
  {
    id: 'ramen_clean_2',
    name: '小高拉麵',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: false,
    csvContent: ramen_clean_2,
  },
  {
    id: 'ramen_clean_3',
    name: '隱家拉麵公館',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: false,
    csvContent: ramen_clean_3,
  },

  // Restaurant (Bento) - Washed
  {
    id: 'bento_washed_1',
    name: '城市盒子寧波',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: true,
    csvContent: bento_washed_1,
  },
  {
    id: 'bento_washed_2',
    name: '村民餐盒',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: true,
    csvContent: bento_washed_2,
  },
  {
    id: 'bento_washed_3',
    name: '米泰豐便當',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: true,
    csvContent: bento_washed_3,
  },
  // Restaurant (Bento) - Clean
  {
    id: 'bento_clean_1',
    name: 'lulu原型餐盒',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: false,
    csvContent: bento_clean_1,
  },
  {
    id: 'bento_clean_2',
    name: '餵way',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: false,
    csvContent: bento_clean_2,
  },
  {
    id: 'bento_clean_3',
    name: '龍城',
    category: 'restaurant',
    categoryLabel: '餐廳',
    isWashed: false,
    csvContent: bento_clean_3,
  },

  // Drinks - Washed
  {
    id: 'drink_washed_1',
    name: '深夜茶飲',
    category: 'drinks',
    categoryLabel: '飲料店',
    isWashed: true,
    csvContent: drink_washed_1,
  },
  {
    id: 'drink_washed_2',
    name: '發發公館牧場',
    category: 'drinks',
    categoryLabel: '飲料店',
    isWashed: true,
    csvContent: drink_washed_2,
  },
  {
    id: 'drink_washed_3',
    name: '茶沐',
    category: 'drinks',
    categoryLabel: '飲料店',
    isWashed: true,
    csvContent: drink_washed_3,
  },
  // Drinks - Clean
  {
    id: 'drink_clean_1',
    name: '可不可公館',
    category: 'drinks',
    categoryLabel: '飲料店',
    isWashed: false,
    csvContent: drink_clean_1,
  },
  {
    id: 'drink_clean_2',
    name: '清心師大',
    category: 'drinks',
    categoryLabel: '飲料店',
    isWashed: false,
    csvContent: drink_clean_2,
  },
  {
    id: 'drink_clean_3',
    name: '迷客夏延吉',
    category: 'drinks',
    categoryLabel: '飲料店',
    isWashed: false,
    csvContent: drink_clean_3,
  },
];
