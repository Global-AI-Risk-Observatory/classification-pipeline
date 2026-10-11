import RegulationTimelineStory from '@/components/regulation-timeline-story';
import { loadFilingMetrics, loadFilingsByMonth, loadRegulationTimeline } from '@/lib/regulation-timeline';

const WINDOW_START = '2025-01-02';
const WINDOW_END = '2025-06-30';

export const metadata = {
  title: 'Timeline Beta | AI Risk Observatory',
  description: 'Scroll through AI and tech regulation events in the US, EU and China alongside the US filing corpus.',
};

export default function TimelineBetaPage() {
  const timeline = loadRegulationTimeline();
  const filings = loadFilingsByMonth();
  const metrics = loadFilingMetrics();

  return (
    <div className="min-h-screen bg-white text-primary">
      <header className="border-b border-border bg-white">
        <div className="mx-auto max-w-7xl px-6 py-14">
          <span className="aisi-tag">Timeline Beta</span>
          <h1 className="text-4xl font-bold tracking-tight">Regulation, month by month</h1>
          <p className="mt-4 max-w-3xl text-lg text-muted">
            Scroll through the dated regulatory events in the US, EU and China. The panel on the right follows your reading
            position and shows where the US filing corpus stands at that point in time.
          </p>
          <p className="mt-3 text-xs text-muted-foreground">
            Events as of {timeline.asOf}. Filing counts from {filings.source} (field {filings.field}), as of {filings.asOf}.
          </p>
        </div>
      </header>
      <RegulationTimelineStory
        events={timeline.events}
        filingsByMonth={filings.months}
        metrics={metrics}
        windowStart={WINDOW_START}
        windowEnd={WINDOW_END}
      />
    </div>
  );
}
