// Shared formatters for human-facing labels.
// Used by AskView (result table headers) and AnalyticsView (histogram titles).

// Map of lowercase tokens → canonical casing for acronyms / unit suffixes
// that should not be title-cased ("eur" → "EUR", not "Eur"). Extend as the
// LLM aliases new vocabulary.
const COLUMN_CASING = {
  // Currencies
  eur: 'EUR', usd: 'USD', gbp: 'GBP', inr: 'INR',
  // Units
  mah: 'mAh', gb: 'GB', mb: 'MB', tb: 'TB', kb: 'KB',
  cm: 'cm', mm: 'mm', kg: 'kg', ml: 'ml',
  // Tech
  ram: 'RAM', cpu: 'CPU', gpu: 'GPU', os: 'OS', ppi: 'PPI', sim: 'SIM',
  rom: 'ROM', id: 'ID', url: 'URL', api: 'API', sql: 'SQL',
  // Network generations / standards
  '2g': '2G', '3g': '3G', '4g': '4G', '5g': '5G',
  cdma: 'CDMA', gsm: 'GSM', lte: 'LTE', hspa: 'HSPA', evdo: 'EVDO',
}

export function humanizeColumnName(name) {
  if (!name) return name
  // If it's already mixed-case (e.g. an alias the LLM wrote as "Brand Name"),
  // leave it alone. Only transform snake_case / all-lowercase names.
  if (!/_/.test(name) && /[A-Z]/.test(name)) return name
  return name
    .replace(/_/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase()
      if (lower in COLUMN_CASING) return COLUMN_CASING[lower]
      return lower.charAt(0).toUpperCase() + lower.slice(1)
    })
    .join(' ')
}
