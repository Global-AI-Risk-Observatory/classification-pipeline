import RegulationTimeline from '@/components/regulation-timeline';
import { loadFilingsByMonth, loadRegulationTimeline } from '@/lib/regulation-timeline';

const WINDOW_START = '2025-01-02';
const WINDOW_END = '2025-06-30';

export const metadata = {
  title: 'Regulation Timeline | AI Risk Observatory',
  description: 'AI and tech regulation events in the US, EU and China against the US filing corpus.',
};

export default function TimelinePage() {
  const timeline = loadRegulationTimeline();
  const filings = loadFilingsByMonth();

  const counts = timeline.events.reduce(
    (acc, e) => {
      acc[e.jurisdiction] += 1;
      if (e.status === 'VERIFIED') acc.verified += 1;
      return acc;
    },
    { US: 0, EU: 0, CN: 0, verified: 0 }
  );

  return (
    <div className="min-h-screen bg-white text-primary">
      <header className="border-b border-border bg-white">
        <div className="mx-auto max-w-7xl px-6 py-14">
          <span className="aisi-tag">Regulation Timeline</span>
          <h1 className="text-4xl font-bold tracking-tight">AI and tech regulation: US, EU, China</h1>
          <p className="mt-4 max-w-3xl text-lg text-muted">
            Dated regulatory events plotted against the US 10-K corpus in the filings bucket. Every event cites a primary source and
            carries a VERIFIED or UNVERIFIED status.
          </p>
          <div className="mt-8 grid grid-cols-2 gap-6 border-t border-border/80 pt-5 sm:grid-cols-5">
            <div>
              <div className="text-2xl font-bold">{timeline.eventCount}</div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Events</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{counts.verified}</div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Verified</div>
            </div>
            <div>
              <div className="text-2xl font-bold">
                {counts.US} / {counts.EU} / {counts.CN}
              </div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">US / EU / CN</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{filings.totalFilings.toLocaleString('en-US')}</div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">US filings</div>
            </div>
            <div>
              <div className="text-2xl font-bold">
                {filings.months[0]?.month} to {filings.months[filings.months.length - 1]?.month}
              </div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Filing window</div>
            </div>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Events as of {timeline.asOf}. Filing counts from {filings.source} (field {filings.field}), as of {filings.asOf}.
          </p>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-6 py-10">
        <RegulationTimeline
          events={timeline.events}
          filingsByMonth={filings.months}
          windowStart={WINDOW_START}
          windowEnd={WINDOW_END}
        />
      </section>
    </div>
  );
}
