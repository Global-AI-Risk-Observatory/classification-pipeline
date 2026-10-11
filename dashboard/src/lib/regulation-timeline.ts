import fs from 'fs';
import path from 'path';

export type RegulationEvent = {
  id: string;
  date: string | null;
  datePrecision: 'day' | 'year' | 'unknown';
  dateLabel: string;
  jurisdiction: 'US' | 'EU' | 'CN';
  track: string;
  instrument: string;
  effect: string;
  sourceUrls: string[];
  sourceNote: string;
  status: 'VERIFIED' | 'UNVERIFIED' | 'UNKNOWN';
  statusNote: string;
};

export type RegulationTimelineData = {
  generatedFrom: string;
  asOf: string | null;
  eventCount: number;
  events: RegulationEvent[];
};

export type FilingMonth = { month: string; filings: number };

export type FilingsByMonthData = {
  source: string;
  field: string;
  asOf: string;
  totalFilings: number;
  uniqueCiks: number;
  filingTypes: Record<string, number>;
  months: FilingMonth[];
};

const dataDir = path.join(process.cwd(), 'data');

export function loadRegulationTimeline(): RegulationTimelineData {
  const raw = fs.readFileSync(path.join(dataDir, 'regulation-timeline.json'), 'utf8');
  return JSON.parse(raw) as RegulationTimelineData;
}

export function loadFilingsByMonth(): FilingsByMonthData {
  const raw = fs.readFileSync(path.join(dataDir, 'us-filings-by-month.json'), 'utf8');
  return JSON.parse(raw) as FilingsByMonthData;
}

export type FilingMetricMonth = {
  month: string;
  filingsTotal?: number;
  filings: number;
  aiMentionShare?: number | null;
  aiRiskShare?: number | null;
  llmAdoptionShare?: number | null;
  cyberRiskShare?: number | null;
};

export type FilingMetricsData = {
  source: string;
  runId: string;
  asOf: string;
  chunksTotal?: number;
  chunksClassified?: number;
  filingsTotal?: number;
  filingsCovered?: number;
  months: FilingMetricMonth[];
};

// Optional: produced by the classification pipeline for the US corpus.
// Returns null until a US run has been exported to data/us-filing-metrics.json.
export function loadFilingMetrics(): FilingMetricsData | null {
  const file = path.join(dataDir, 'us-filing-metrics.json');
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, 'utf8')) as FilingMetricsData;
}
