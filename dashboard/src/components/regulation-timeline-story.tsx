'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { FilingMetricsData, FilingMonth, RegulationEvent } from '@/lib/regulation-timeline';

type Jurisdiction = RegulationEvent['jurisdiction'];

const JURISDICTION_META: Record<Jurisdiction, { label: string; color: string }> = {
  US: { label: 'United States', color: '#e63946' },
  EU: { label: 'European Union', color: '#1d4ed8' },
  CN: { label: 'China', color: '#b45309' },
};

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const formatMonth = (month: string) => {
  const [y, m] = month.split('-').map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
};

const formatDay = (date: string) => {
  const [y, m, d] = date.split('-').map(Number);
  return `${d} ${MONTH_NAMES[m - 1]} ${y}`;
};

const pct = (value: number | null | undefined) => (value == null ? null : `${Math.round(value * 100)}%`);

interface Props {
  events: RegulationEvent[];
  filingsByMonth: FilingMonth[];
  metrics: FilingMetricsData | null;
  windowStart: string;
  windowEnd: string;
}

export default function RegulationTimelineStory({ events, filingsByMonth, metrics, windowStart, windowEnd }: Props) {
  const [activeJurisdictions, setActiveJurisdictions] = useState<Set<Jurisdiction>>(new Set(['US', 'EU', 'CN']));
  const [currentMonth, setCurrentMonth] = useState<string | null>(null);
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map());

  const filtered = useMemo(
    () => events.filter(e => e.date && activeJurisdictions.has(e.jurisdiction)),
    [events, activeJurisdictions]
  );

  const months = useMemo(() => {
    const map = new Map<string, RegulationEvent[]>();
    for (const e of filtered) {
      const key = (e.date as string).slice(0, 7);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(e);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  useEffect(() => {
    const first = months[0]?.[0] ?? null;
    const frame = window.requestAnimationFrame(() => setCurrentMonth(prev => prev ?? first));
    return () => window.cancelAnimationFrame(frame);
  }, [months]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        const visible = entries
          .filter(entry => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const top = visible[0]?.target as HTMLElement | undefined;
        if (top?.dataset.month) setCurrentMonth(top.dataset.month);
      },
      { rootMargin: '-35% 0px -55% 0px', threshold: 0 }
    );
    sectionRefs.current.forEach(el => observer.observe(el));
    return () => observer.disconnect();
  }, [months]);

  const filingsMap = useMemo(() => new Map(filingsByMonth.map(m => [m.month, m.filings])), [filingsByMonth]);
  const metricsMap = useMemo(() => new Map((metrics?.months ?? []).map(m => [m.month, m])), [metrics]);
  const totalFilings = filingsByMonth.reduce((sum, m) => sum + m.filings, 0);
  const windowStartMonth = windowStart.slice(0, 7);
  const windowEndMonth = windowEnd.slice(0, 7);

  const state = useMemo(() => {
    if (!currentMonth) return null;
    const filedToDate = filingsByMonth.filter(m => m.month <= currentMonth).reduce((s, m) => s + m.filings, 0);
    const thisMonth = filingsMap.get(currentMonth) ?? 0;
    const position =
      currentMonth < windowStartMonth ? 'before' : currentMonth > windowEndMonth ? 'after' : 'inside';
    return { filedToDate, thisMonth, position, metric: metricsMap.get(currentMonth) ?? null };
  }, [currentMonth, filingsByMonth, filingsMap, metricsMap, windowStartMonth, windowEndMonth]);

  const allMonths = months.map(([m]) => m);
  const firstMonth = allMonths[0];
  const lastMonth = allMonths[allMonths.length - 1];
  const monthIndex = (m: string) => {
    const [y, mo] = m.split('-').map(Number);
    return y * 12 + (mo - 1);
  };
  const span = firstMonth && lastMonth ? monthIndex(lastMonth) - monthIndex(firstMonth) || 1 : 1;
  const toPct = (m: string) => (firstMonth ? ((monthIndex(m) - monthIndex(firstMonth)) / span) * 100 : 0);

  return (
    <div className="mx-auto max-w-7xl px-6">
      <div className="flex flex-wrap items-center gap-2 border-b border-border py-4">
        <span className="mr-2 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Show</span>
        {(Object.keys(JURISDICTION_META) as Jurisdiction[]).map(key => {
          const active = activeJurisdictions.has(key);
          const meta = JURISDICTION_META[key];
          return (
            <button
              key={key}
              type="button"
              onClick={() =>
                setActiveJurisdictions(prev => {
                  const next = new Set(prev);
                  if (next.has(key)) next.delete(key);
                  else next.add(key);
                  return next;
                })
              }
              className={`inline-flex items-center gap-2 rounded border px-3 py-1.5 text-xs font-semibold transition-colors ${
                active ? 'border-transparent text-white' : 'border-border bg-white text-muted-foreground'
              }`}
              style={active ? { backgroundColor: meta.color } : undefined}
            >
              {meta.label}
            </button>
          );
        })}
        <span className="ml-auto text-xs text-muted-foreground">{filtered.length} events</span>
      </div>

      <div className="grid gap-10 py-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* Narrative */}
        <div>
          {months.map(([month, monthEvents]) => {
            const inWindow = month >= windowStartMonth && month <= windowEndMonth;
            return (
              <section
                key={month}
                data-month={month}
                ref={el => {
                  if (el) sectionRefs.current.set(month, el);
                  else sectionRefs.current.delete(month);
                }}
                className="border-l-2 border-border pb-14 pl-8"
              >
                <div className="relative">
                  <span
                    className={`absolute -left-[41px] top-1 h-4 w-4 rounded-full border-2 border-white ${
                      inWindow ? 'bg-accent' : 'bg-muted-foreground'
                    }`}
                  />
                  <h2 className="text-2xl font-bold tracking-tight text-primary sm:text-3xl">{formatMonth(month)}</h2>
                  <p className="mt-1 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {inWindow
                      ? `${(filingsMap.get(month) ?? 0).toLocaleString('en-US')} US filings filed this month`
                      : month < windowStartMonth
                        ? 'Before the filing window'
                        : 'After the filing window'}
                  </p>
                </div>

                <div className="mt-6 space-y-6">
                  {monthEvents.map(e => {
                    const meta = JURISDICTION_META[e.jurisdiction];
                    return (
                      <article key={e.id} className="rounded-lg border border-border bg-white p-5">
                        <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em]">
                          <span className="rounded px-2 py-0.5 text-white" style={{ backgroundColor: meta.color }}>
                            {meta.label}
                          </span>
                          <span className="text-muted-foreground">{e.track}</span>
                          <span className="ml-auto font-mono text-muted-foreground">
                            {e.datePrecision === 'day' ? formatDay(e.date as string) : e.dateLabel}
                          </span>
                        </div>
                        <h3 className="mt-3 text-lg font-bold leading-snug text-primary">{e.instrument}</h3>
                        <p className="mt-2 text-base leading-relaxed text-muted">{e.effect}</p>
                        <details className="mt-3 text-xs">
                          <summary className="cursor-pointer font-semibold text-muted-foreground hover:text-primary">
                            Source and verification
                          </summary>
                          <div className="mt-2 space-y-1 border-l-2 border-border pl-3">
                            <p>
                              Status:{' '}
                              <span className={e.status === 'VERIFIED' ? 'text-emerald-700' : 'text-amber-700'}>{e.statusNote}</span>
                            </p>
                            {e.sourceUrls.length > 0 ? (
                              e.sourceUrls.map(url => (
                                <a
                                  key={url}
                                  href={url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="block break-all underline decoration-border underline-offset-2 hover:text-primary"
                                >
                                  {url}
                                </a>
                              ))
                            ) : (
                              <p className="text-muted-foreground">{e.sourceNote}</p>
                            )}
                          </div>
                        </details>
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>

        {/* Sticky state panel */}
        <aside className="hidden lg:block">
          <div className="sticky top-24 space-y-4">
            <div className="rounded-lg border border-border bg-white p-5">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Reading position</p>
              <p className="mt-1 text-2xl font-bold text-primary">{currentMonth ? formatMonth(currentMonth) : '—'}</p>

              <div className="relative mt-4 h-8">
                {firstMonth && (
                  <>
                    <div
                      className="absolute top-3 h-2 bg-red-100"
                      style={{ left: `${toPct(windowStartMonth)}%`, width: `${Math.max(toPct(windowEndMonth) - toPct(windowStartMonth), 1)}%` }}
                      title="US filing window"
                    />
                    <div className="absolute top-[15px] h-px w-full bg-border" />
                    {allMonths.map(m => (
                      <span
                        key={m}
                        className="absolute top-[13px] h-[5px] w-[5px] rounded-full bg-muted-foreground/60"
                        style={{ left: `${toPct(m)}%` }}
                      />
                    ))}
                    {currentMonth && (
                      <span
                        className="absolute top-[9px] h-[13px] w-[13px] -translate-x-1/2 rounded-full border-2 border-white bg-accent shadow"
                        style={{ left: `${toPct(currentMonth)}%` }}
                      />
                    )}
                  </>
                )}
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>{firstMonth}</span>
                <span className="text-accent">filing window</span>
                <span>{lastMonth}</span>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-white p-5">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">US filing corpus at this point</p>
              {state && (
                <dl className="mt-3 space-y-3">
                  <div>
                    <dt className="text-xs text-muted">Filings filed to date</dt>
                    <dd className="text-2xl font-bold text-primary">
                      {state.filedToDate.toLocaleString('en-US')}
                      <span className="ml-1 text-sm font-normal text-muted-foreground">of {totalFilings.toLocaleString('en-US')}</span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted">Filings this month</dt>
                    <dd className="text-2xl font-bold text-primary">
                      {state.position === 'inside' ? state.thisMonth.toLocaleString('en-US') : '0'}
                    </dd>
                  </div>
                  <div className="h-10">
                    <div className="flex h-full items-end gap-[2px]">
                      {filingsByMonth.map(m => {
                        const max = Math.max(...filingsByMonth.map(x => x.filings));
                        const reached = currentMonth ? m.month <= currentMonth : false;
                        return (
                          <div
                            key={m.month}
                            title={`${m.month}: ${m.filings}`}
                            className={`flex-1 rounded-t ${reached ? 'bg-accent' : 'bg-border'}`}
                            style={{ height: `${(m.filings / max) * 100}%` }}
                          />
                        );
                      })}
                    </div>
                  </div>
                </dl>
              )}
            </div>

            <div className="rounded-lg border border-border bg-white p-5">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Disclosure signals this month</p>
              {state?.metric ? (
                <dl className="mt-3 grid grid-cols-2 gap-3">
                  {[
                    ['AI mention', state.metric.aiMentionShare],
                    ['AI risk', state.metric.aiRiskShare],
                    ['LLM adoption', state.metric.llmAdoptionShare],
                    ['Cyber risk', state.metric.cyberRiskShare],
                  ].map(([label, value]) => (
                    <div key={label as string}>
                      <dt className="text-xs text-muted">{label as string}</dt>
                      <dd className="text-xl font-bold text-primary">{pct(value as number | null | undefined) ?? '—'}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="mt-3 text-sm text-muted">
                  {metrics
                    ? 'No classified filings for this month.'
                    : 'Not available yet. Populated from data/us-filing-metrics.json once the classification pipeline has run on the US corpus.'}
                </p>
              )}
              {state?.metric && (
                <p className="mt-3 text-xs text-muted">
                  Based on {state.metric.filings.toLocaleString('en-US')} classified filings
                  {state.metric.filingsTotal != null && ` of ${state.metric.filingsTotal.toLocaleString('en-US')} filed this month`}.
                </p>
              )}
              {metrics && (
                <p className="mt-3 text-[10px] text-muted-foreground">
                  Run {metrics.runId}, as of {metrics.asOf}
                  {metrics.chunksClassified != null && metrics.chunksTotal != null && `, ${metrics.chunksClassified.toLocaleString('en-US')} of ${metrics.chunksTotal.toLocaleString('en-US')} chunks classified`}.
                </p>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
