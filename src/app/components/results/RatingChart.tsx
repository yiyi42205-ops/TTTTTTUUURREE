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
    <div>
      <h3 className="text-sm font-semibold text-ink mb-4 tracking-tight">
        星級分佈對比
        <span className="text-ink-tertiary font-normal ml-2 text-xs font-mono tracking-wider">RATING DISTRIBUTION</span>
      </h3>
      <div className="h-52 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={distData} margin={{ top: 5, right: 5, left: -28, bottom: 5 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              vertical={false}
              stroke="var(--hairline)"
            />
            <XAxis
              dataKey="star"
              tick={{ fontSize: 11, fill: 'var(--ink-subtle)', fontWeight: 500 }}
              stroke="var(--hairline)"
              axisLine={{ stroke: 'var(--hairline-strong)' }}
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
                backgroundColor: 'var(--surface-1)',
                borderRadius: '4px',
                border: '1px solid var(--hairline-strong)',
                fontSize: '12px',
                fontWeight: 500,
                color: 'var(--ink)',
                boxShadow: 'none',
              }}
              itemStyle={{ color: 'var(--ink-muted)' }}
              cursor={{ fill: 'var(--surface-2)', opacity: 0.5 }}
            />
            <Bar
              dataKey="原始"
              fill="var(--hairline-strong)"
              radius={[2, 2, 0, 0]}
              barSize={18}
            />
            <Bar
              dataKey="校正後"
              fill="var(--ink)"
              radius={[2, 2, 0, 0]}
              barSize={18}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center justify-center gap-5 mt-3 text-xs text-ink-subtle">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: 'var(--hairline-strong)' }} />
          原始
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-ink" />
          校正後
        </span>
      </div>
    </div>
  );
}
