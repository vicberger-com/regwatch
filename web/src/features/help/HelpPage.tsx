import { useLocation } from "@tanstack/react-router";
import { useEffect } from "react";

import { AREAS, TOPICS } from "./topics";

/**
 * `/help`: the second layer of the help tips. Every element that has a tip has a section here;
 * a "Learn more" link opens this page at its section and moves focus to its heading.
 */
export function HelpPage() {
  const hash = useLocation({ select: (l) => l.hash });
  useEffect(() => {
    if (!hash) return;
    const heading = document.getElementById(hash);
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- absent in jsdom
    heading?.scrollIntoView?.({ block: "start" });
    heading?.focus();
  }, [hash]);
  return (
    <>
      <h1 className="text-2xl font-semibold">Help</h1>
      <p className="mt-2 max-w-prose text-text-muted">
        What each setting and choice does. The ⓘ button beside a setting opens a
        short tip, and its link leads here.
      </p>
      <nav aria-label="Help sections" className="mt-4">
        <ul className="flex flex-wrap gap-4">
          {AREAS.filter((a) => TOPICS.some((t) => t.area === a)).map((area) => (
            <li key={area}>
              <a
                href={`#area-${area.replace(/\s+/g, "-")}`}
                className="text-accent underline"
              >
                {area}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      {AREAS.map((area) => {
        const topics = TOPICS.filter((t) => t.area === area);
        if (topics.length === 0) return null;
        return (
          <section
            key={area}
            aria-labelledby={`area-${area.replace(/\s+/g, "-")}`}
            className="mt-8 max-w-prose"
          >
            <h2
              id={`area-${area.replace(/\s+/g, "-")}`}
              className="text-xl font-semibold"
            >
              {area}
            </h2>
            {topics.map((t) => (
              <article key={t.id} className="mt-4 border-t border-border pt-3">
                <h3 id={t.id} tabIndex={-1} className="font-semibold">
                  {t.title}
                </h3>
                <p className="mt-1">{t.tip}</p>
                {t.body.map((text, i) => (
                  <p key={i} className="mt-1 text-text-muted">
                    {text}
                  </p>
                ))}
              </article>
            ))}
          </section>
        );
      })}
    </>
  );
}
