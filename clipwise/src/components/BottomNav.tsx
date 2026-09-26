"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookmarkIcon, FeedIcon, PlusIcon, SettingsIcon, TopicsIcon } from "./icons";

const ITEMS = [
  { href: "/", label: "Feed", Icon: FeedIcon, match: (p: string) => p === "/" },
  { href: "/saved", label: "Saved", Icon: BookmarkIcon, match: (p: string) => p.startsWith("/saved") },
  { href: "/topics", label: "Topics", Icon: TopicsIcon, match: (p: string) => p.startsWith("/topics") },
  {
    href: "/ingest",
    label: "Add",
    Icon: PlusIcon,
    match: (p: string) => p.startsWith("/ingest") || p.startsWith("/library") || p.startsWith("/clips"),
  },
  { href: "/settings", label: "Settings", Icon: SettingsIcon, match: (p: string) => p.startsWith("/settings") },
];

export function BottomNav() {
  const pathname = usePathname() ?? "/";
  if (pathname.startsWith("/watch")) return null;
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-ink/80 backdrop-blur-xl"
      style={{ paddingBottom: "var(--safe-bottom)" }}
    >
      <ul className="mx-auto flex h-[var(--nav-h)] max-w-lg items-stretch justify-around">
        {ITEMS.map(({ href, label, Icon, match }) => {
          const active = match(pathname);
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex h-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors ${
                  active ? "text-white" : "text-white/45 hover:text-white/75"
                }`}
              >
                <Icon size={22} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
