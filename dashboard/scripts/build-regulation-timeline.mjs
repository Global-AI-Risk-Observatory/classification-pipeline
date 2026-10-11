// Builds data/regulation-timeline.json from docs/regulation-timeline.md.
// The markdown file is the editable source (one table per track); this script
// turns its rows into structured events the dashboard can filter and plot.
//
// Usage: node ./scripts/build-regulation-timeline.mjs [path/to/regulation-timeline.md]

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.resolve(here, '..', '..', 'docs', 'regulation-timeline.md');
const outputPath = path.resolve(here, '..', 'data', 'regulation-timeline.json');

const TRACKS = [
  { heading: '## 2. US: federal, Congress, states, export controls', jurisdiction: 'US', track: 'US federal, Congress, states, export controls' },
  { heading: '## 3. US: agencies and courts', jurisdiction: 'US', track: 'US agencies and courts' },
  { heading: '## 4. EU', jurisdiction: 'EU', track: 'EU' },
  { heading: '## 5. China', jurisdiction: 'CN', track: 'China' },
];

const markdown = fs.readFileSync(sourcePath, 'utf8');
const lines = markdown.split('\n');

const asOfMatch = markdown.match(/As of (\d{4}-\d{2}-\d{2})/);
const asOf = asOfMatch ? asOfMatch[1] : null;

const splitRow = line =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim());

const parseDate = raw => {
  const iso = raw.match(/\d{4}-\d{2}-\d{2}/);
  if (iso) return { date: iso[0], precision: 'day' };
  const year = raw.match(/\d{4}/);
  if (year) return { date: `${year[0]}-01-01`, precision: 'year' };
  return { date: null, precision: 'unknown' };
};

const extractUrls = text => Array.from(text.matchAll(/https?:\/\/[^\s)]+/g)).map(m => m[0]);

const events = [];
let current = null;

for (const line of lines) {
  const track = TRACKS.find(t => line.trim() === t.heading);
  if (track) {
    current = track;
    continue;
  }
  if (line.startsWith('## ')) {
    current = null;
    continue;
  }
  if (!current || !line.startsWith('|')) continue;

  const cells = splitRow(line);
  if (cells.length < 5) continue;
  if (cells[0] === 'Date' || /^-+$/.test(cells[0])) continue;

  const [dateRaw, instrument, effect, sourceRaw, statusRaw] = cells;
  const { date, precision } = parseDate(dateRaw);
  const statusWord = statusRaw.startsWith('UNVERIFIED') ? 'UNVERIFIED' : statusRaw.startsWith('VERIFIED') ? 'VERIFIED' : 'UNKNOWN';

  events.push({
    id: `${current.jurisdiction.toLowerCase()}-${events.length + 1}`,
    date,
    datePrecision: precision,
    dateLabel: dateRaw,
    jurisdiction: current.jurisdiction,
    track: current.track,
    instrument,
    effect,
    sourceUrls: extractUrls(sourceRaw),
    sourceNote: sourceRaw,
    status: statusWord,
    statusNote: statusRaw,
  });
}

events.sort((a, b) => (a.date ?? '').localeCompare(b.date ?? ''));

const output = {
  generatedFrom: path.relative(path.resolve(here, '..', '..'), sourcePath),
  asOf,
  eventCount: events.length,
  events,
};

fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
console.log(`Wrote ${events.length} events to ${path.relative(process.cwd(), outputPath)}`);
