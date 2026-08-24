import { motion } from 'motion/react';
import { ResponsiveContainer, BarChart, CartesianGrid, XAxis, YAxis, Tooltip, Bar } from 'recharts';
import type { ShopStats } from '../../utils/auditEngine';

interface RatingChartProps {
  result: ShopStats;
  chartId: string;
}

export function RatingChart({ result, chartId }: RatingChartProps) {
  const distData = [
    { star: '5★', '原始': result.ratingDistribution.original[5] || 0, '校正後': result.ratingDistribution.filtered[5] || 0 },
    { star: '4★', '原始': result.ratingDistribution.original[4] || 0, '校正後': result.ratingDistribution.filtered[4] || 0 },
    { star: '3★', '原始': result.ratingDistribution.original[3] || 0, '校正後': result.ratingDistribution.filtered[3] || 0 },
    { star: '2★', '原始': result.ratingDistribution.original[2] || 0, '校正後': result.ratingDistribution.filtered[2] || 0 },
    { star: '1★', '原始': result.ratingDistribution.original[1] || 0, '校正後': result.ratingDistribution.filtered[1] || 0 },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.15 }}
      className="bg-surface-1 border border-hairline rounded-xl p-4 md:p-5"
    >
      <h3 className="text-sm font-medium text-ink-muted mb-4 tracking-[-0.2px]">
        星級分佈對比
      </h3>
      <div className="h-52 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={distData} margin={{ top: 5, right: 5, left: -28, bottom: 5 }}>
            <defs>
              <linearGradient id={`grad-original-${chartId}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--ink-subtle)" stopOpacity={0.7} />
                <stop offset="100%" stopColor="var(--ink-subtle)" stopOpacity={0.3} />
              </linearGradient>
              <linearGradient id={`grad-corrected-${chartId}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.9} />
                <stop offset="100%" stopColor="var(--primary)" stopOpacity={0.5} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              vertical={false}
              stroke="var(--hairline)"
            />
            <XAxis
              dataKey="star"
              tick={{ fontSize: 11, fill: 'var(--ink-subtle)', fontWeight: 500 }}
              stroke="var(--hairline)"
              axisLine={{ stroke: 'var(--hairline)' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: 'var(--ink-tertiary)' }}
              stroke="var(--hairline)"
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--surface-2)',
                borderRadius: '8px',
                border: '1px solid var(--hairline)',
                fontSize: '12px',
                fontWeight: 500,
                color: 'var(--ink)',
                boxShadow: 'none',
              }}
              itemStyle={{ color: 'var(--ink-muted)' }}
              cursor={{ fill: 'var(--surface-3)', opacity: 0.5 }}
            />
            <Bar
              dataKey="原始"
              fill={`url(#grad-original-${chartId})`}
              radius={[4, 4, 0, 0]}
              barSize={18}
            />
            <Bar
              dataKey="校正後"
              fill={`url(#grad-corrected-${chartId})`}
              radius={[4, 4, 0, 0]}
              barSize={18}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center justify-center gap-5 mt-3 text-xs text-ink-subtle">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-ink-subtle/50" />
          原始
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-primary" />
          校正後
        </span>
      </div>
    </motion.div>
  );
}
