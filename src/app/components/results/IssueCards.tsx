import { motion } from 'motion/react';
import { Gift, Copy, MessageSquareWarning } from 'lucide-react';
import type { ShopStats } from '../../utils/auditEngine';

interface IssueCardsProps {
  result: ShopStats;
}

export function IssueCards({ result }: IssueCardsProps) {
  const cards = [
    {
      label: '促銷型',
      sublabel: 'Incentive',
      count: result.issues.timeAnomaly,
      icon: Gift,
      color: 'text-[var(--semantic-danger)]',
      bg: 'bg-[var(--semantic-danger)]/10',
    },
    {
      label: '模板型',
      sublabel: 'Template',
      count: result.issues.templateText,
      icon: Copy,
      color: 'text-[var(--semantic-warning)]',
      bg: 'bg-[var(--semantic-warning)]/10',
    },
    {
      label: '語意矛盾',
      sublabel: 'Discrepancy',
      count: result.issues.vague,
      icon: MessageSquareWarning,
      color: 'text-primary',
      bg: 'bg-primary/10',
    },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((card, i) => {
        const Icon = card.icon;
        return (
          <motion.div
            key={card.sublabel}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1 + i * 0.05 }}
            className="bg-surface-2 border border-hairline rounded-xl p-4 text-center"
          >
            <div className={`inline-flex items-center justify-center w-8 h-8 rounded-lg ${card.bg} mb-2`}>
              <Icon className={`w-4 h-4 ${card.color}`} />
            </div>
            <div className={`text-2xl font-semibold tracking-[-0.6px] ${card.color} mb-0.5`}>
              {card.count}
            </div>
            <div className="text-xs text-ink-muted font-medium">{card.label}</div>
            <div className="text-[10px] text-ink-tertiary">{card.sublabel}</div>
          </motion.div>
        );
      })}
    </div>
  );
}
