'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  { href: '/timeline-beta', label: 'Timeline Beta' },
  { href: '/timeline', label: 'Regulation Timeline' },
];

export function PageNav() {
  const pathname = usePathname();
  return (
    <nav className="sticky top-0 z-50 border-b border-border bg-white/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-10 gap-y-3 px-6 py-4">
        <Link href="/timeline-beta" className="text-lg font-bold tracking-tight text-primary">
          AI Risk Observatory
        </Link>
        <div className="flex flex-wrap items-center gap-x-8">
          {links.map(link => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`relative py-1 text-sm font-semibold transition-colors ${
                  isActive ? 'text-accent' : 'text-muted-foreground hover:text-primary'
                }`}
              >
                {link.label}
                {isActive && <span className="absolute inset-x-0 bottom-0 h-1 bg-accent" />}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
