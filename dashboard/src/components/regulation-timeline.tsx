'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { FilingMonth, RegulationEvent } from '@/lib/regulation-timeline';

type Jurisdiction = RegulationEvent['jurisdiction'];

const JURISDICTIONS: { key: Jurisdiction; label: string; color: string }[] = [
  { key: 'US', label: 'United States', color: '#e63946' },
  { key: 'EU', label: 'European Union', color: '#1d4ed8' },
  { key: 'CN', label: 'China', color: '#b45309' },
];

const COLOR_BY_JURISDICTION = Object.fromEntries(JURISDICTIONS.map(j => [j.key, j.color])) as Record<Jurisdiction, string>;

type RangeKey = 'window' | '2024-2026' | 'all';

const RANGES: { key: RangeKey; label: string }[] = [
  { key: 'window', label: 'Data window (2025-01 to 2025-06)' },
  { key: '2024-2026', label: '2024 to 2026' },
  { key: 'all', label: 'All events' },
];

interface Props {
  events: RegulationEvent[];
  filingsByMonth: FilingMonth[];
  windowStart: string; // YYYY-MM-DD
  windowEnd: string; // YYYY-MM-DD
}

const monthOf = (date: string) => date.slice(0, 7);

const monthsBetween = (startMonth: string, endMonth: string) => {
  const out: string[] = [];
  let [y, m] = startMonth.split('-').map(Number);
  const [ey, em] = endMonth.split('-').map(Number);
  while (y < ey || (y === ey && m <= em)) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out;
};

export default function RegulationTimeline({ events, filingsByMonth, windowStart, windowEnd }: Props) {
  const [activeJurisdictions, setActiveJurisdictions] = useState<Set<Jurisdiction>>(new Set(['US', 'EU', 'CN']));
  const [activeTracks, setActiveTracks] = useState<Set<string>>(() => new Set(events.map(e => e.track)));
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [range, setRange] = useState<RangeKey>('window');
  const [query, setQuery] = useState('');
  const [hasMounted, setHasMounted] = useState(false);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setHasMounted(true);
    });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, []);

  const tracks = useMemo(() => Array.from(new Set(events.map(e => e.track))), [events]);

  const toggle = <T,>(set: Set<T>, value: T) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return events.filter(e => {
      if (!activeJurisdictions.has(e.jurisdiction)) return false;
      if (!activeTracks.has(e.track)) return false;
      if (verifiedOnly && e.status !== 'VERIFIED') return false;
      if (q && !`${e.instrument} ${e.effect} ${e.dateLabel}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [events, activeJurisdictions, activeTracks, verifiedOnly, query]);

  const [rangeStart, rangeEnd] = useMemo(() => {
    if (range === 'window') return [monthOf(windowStart), monthOf(windowEnd)];
    if (range === '2024-2026') return ['2024-01', '2026-12'];
    const dates = events.map(e => e.date).filter((d): d is string => Boolean(d)).sort();
    return [monthOf(dates[0]), monthOf(dates[dates.length - 1])];
  }, [range, events, windowStart, windowEnd]);

  const chartMonths = useMemo(() => monthsBetween(rangeStart, rangeEnd), [rangeStart, rangeEnd]);

  const filingsMap = useMemo(() => new Map(filingsByMonth.map(m => [m.month, m.filings])), [filingsByMonth]);

  const eventsByMonth = useMemo(() => {
    const map = new Map<string, RegulationEvent[]>();
    for (const e of filtered) {
      if (!e.date) continue;
      const key = monthOf(e.date);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(e);
    }
    return map;
  }, [filtered]);

  const chartData = chartMonths.map(month => ({
    month,
    filings: filingsMap.get(month) ?? 0,
    events: eventsByMonth.get(month) ?? [],
  }));

  const inRange = filtered.filter(e => e.date && monthOf(e.date) >= rangeStart && monthOf(e.date) <= rangeEnd);
  const inWindow = (e: RegulationEvent) => Boolean(e.date && e.date >= windowStart && e.date <= windowEnd);

  const xTickFormatter = (month: string) => {
    if (chartMonths.length <= 12) return month;
    return month.endsWith('-01') ? month.slice(0, 4) : '';
  };

  return (
    <div className="space-y-8">
      {/* Controls */}
      <div className="grid gap-4 rounded-lg border border-border bg-white p-5 md:grid-cols-[1fr_auto]">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-2 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Jurisdiction</span>
            {JURISDICTIONS.map(j => {
              const active = activeJurisdictions.has(j.key);
              return (
                <button
                  key={j.key}
                  type="button"
                  onClick={() => setActiveJurisdictions(s => toggle(s, j.key))}
                  className={`inline-flex items-center gap-2 rounded border px-3 py-1.5 text-xs font-semibold transition-colors ${
                    active ? 'border-transparent text-white' : 'border-border bg-white text-muted-foreground'
                  }`}
                  style={active ? { backgroundColor: j.color } : undefined}
                >
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: active ? '#fff' : j.color }} />
                  {j.label}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-2 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Track</span>
            {tracks.map(t => {
              const active = activeTracks.has(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => setActiveTracks(s => toggle(s, t))}
                  className={`rounded border px-3 py-1.5 text-xs font-semibold transition-colors ${
                    active ? 'border-primary bg-primary text-white' : 'border-border bg-white text-muted-foreground'
                  }`}
                >
                  {t}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-2 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Range</span>
            {RANGES.map(r => (
              <button
                key={r.key}
                type="button"
                onClick={() => setRange(r.key)}
                className={`rounded border px-3 py-1.5 text-xs font-semibold transition-colors ${
                  range === r.key ? 'border-primary bg-primary text-white' : 'border-border bg-white text-muted-foreground'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-3 md:items-end">
          <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
            <input type="checkbox" checked={verifiedOnly} onChange={e => setVerifiedOnly(e.target.checked)} />
            Verified only
          </label>
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search instrument or effect"
            className="w-full rounded border border-border px-3 py-1.5 text-sm md:w-64"
          />
          <p className="text-xs text-muted-foreground">
            {filtered.length} of {events.length} events match. {inRange.length} in the selected range.
          </p>
        </div>
      </div>

      {/* Chart */}
      <div className="rounded-lg border border-border bg-white p-5">
        <h2 className="text-lg font-bold text-primary">US filings per month with regulation events</h2>
        <p className="mt-1 text-sm text-muted">
          Bars: filings in the bucket by filing_date. Vertical lines: events in the selected range, colored by jurisdiction. Hover a month for the event list.
        </p>
        <div className="mt-4 h-80 w-full">
          {hasMounted && (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
              <CartesianGrid stroke="#e5e7eb" vertical={false} />
              <XAxis dataKey="month" tickFormatter={xTickFormatter} tick={{ fontSize: 11 }} interval={0} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const row = payload[0].payload as (typeof chartData)[number];
                  return (
                    <div className="max-w-sm rounded border border-border bg-white p-3 text-xs shadow">
                      <p className="font-bold text-primary">{row.month}</p>
                      <p className="text-muted">Filings: {row.filings}</p>
                      {row.events.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {row.events.map(e => (
                            <li key={e.id} className="flex gap-2">
                              <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: COLOR_BY_JURISDICTION[e.jurisdiction] }} />
                              <span>
                                <span className="font-semibold">{e.date}</span> {e.instrument}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                }}
              />
              <Bar dataKey="filings" fill="#9ca3af" radius={[2, 2, 0, 0]} />
              {inRange.map(e => (
                <ReferenceLine
                  key={e.id}
                  x={monthOf(e.date as string)}
                  stroke={COLOR_BY_JURISDICTION[e.jurisdiction]}
                  strokeDasharray={e.status === 'VERIFIED' ? undefined : '4 3'}
                  strokeOpacity={0.6}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-secondary text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Jurisdiction</th>
              <th className="px-3 py-2">Instrument</th>
              <th className="px-3 py-2">Effect</th>
              <th className="px-3 py-2">In data window</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(e => (
              <tr key={e.id} className="border-t border-border align-top">
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{e.dateLabel}</td>
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-2 text-xs font-semibold">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: COLOR_BY_JURISDICTION[e.jurisdiction] }} />
                    {e.jurisdiction}
                  </span>
                  <div className="text-[10px] text-muted-foreground">{e.track}</div>
                </td>
                <td className="px-3 py-2 font-medium text-primary">{e.instrument}</td>
                <td className="px-3 py-2 text-muted">{e.effect}</td>
                <td className="px-3 py-2 text-xs">{inWindow(e) ? 'Yes' : 'No'}</td>
                <td className="px-3 py-2 text-xs">
                  <span className={e.status === 'VERIFIED' ? 'text-emerald-700' : 'text-amber-700'}>{e.status}</span>
                  {e.statusNote !== e.status && <div className="text-[10px] text-muted-foreground">{e.statusNote}</div>}
                </td>
                <td className="px-3 py-2 text-xs">
                  {e.sourceUrls.length > 0 ? (
                    e.sourceUrls.map((url, i) => (
                      <a
                        key={url}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block max-w-[14rem] truncate underline decoration-border underline-offset-2 hover:text-primary"
                      >
                        {i === 0 ? new URL(url).hostname : `${new URL(url).hostname} (${i + 1})`}
                      </a>
                    ))
                  ) : (
                    <span className="text-muted-foreground">{e.sourceNote}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
