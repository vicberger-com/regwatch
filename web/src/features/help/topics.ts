/**
 * Help topics: the tip (one or two sentences) and the help page's fuller text for each element
 * a settings screen offers. Ids are `area:key`; an element with no topic shows no help button.
 */
export interface Topic {
  id: string;
  area: Area;
  title: string;
  tip: string;
  body: string[];
}

export type Area = "User tab" | "Settings" | "Feature flags" | "Sources";
export const AREAS: Area[] = [
  "User tab",
  "Settings",
  "Feature flags",
  "Sources",
];

const T = (
  area: Area,
  key: string,
  title: string,
  tip: string,
  ...body: string[]
): Topic => ({
  id: `${area === "User tab" ? "me" : area === "Settings" ? "setting" : area === "Feature flags" ? "flag" : "source"}-${key.replace(/[^a-z0-9]+/gi, "-")}`,
  area,
  title,
  tip,
  body,
});

const ME: Topic[] = [
  T(
    "User tab",
    "interests",
    "My interests",
    "The regions, jurisdictions and topics the map, items and search open filtered to; you can always show everything.",
    "Interests are default filters, never a limit: everyone can still see all content. A choice that is later removed from the taxonomy is simply dropped.",
    "If you have set none and you are in a group with interests, the group's are used, and the chip on the map and the items list names the group. Choosing your own takes over.",
  ),
  T(
    "User tab",
    "feeds",
    "Feeds",
    "The curated catalogue of official sources; tick one to follow it, and it is captured for everyone.",
    "The catalogue ships with the application. Each feed is checked before it is listed and always respects the site's robots.txt. A feed is captured while at least one person follows it, and one capture serves everyone.",
    "An administrator can turn a feed off; it then shows as turned off and cannot be followed until it is on again.",
    "To add a feed that is not listed, ask for it with its https address and why it matters. An editor checks the feed and adds it to the catalogue, and you then follow it, or declines with a note. You can withdraw a request while it waits.",
    "legislation.gov.uk refuses requests that give no contact address, so its feed fails until an administrator sets the contact email in Settings.",
  ),
  T(
    "User tab",
    "accessibility_preset",
    "Accessibility mode",
    "Switches on high contrast, larger text and targets, always-visible labels and reduced motion at once.",
    "Accessibility mode is a preset. It fills in the high-contrast theme, 125% text, 44-pixel targets, toolbar labels always shown and reduced motion, for every one of those you have left at its default.",
    "You can still change the theme, text size and motion; your own choice wins over the preset. Toolbar labels and larger targets stay on while the preset is on.",
  ),
  T(
    "User tab",
    "theme",
    "Theme",
    "The colours of the whole application: light, dark, high contrast, or follow your system.",
    "Follow the system uses your operating system's light or dark setting. High contrast uses pure black and white with stronger borders, and adds hatch patterns to the map so its colours are not the only signal.",
    "The theme is saved with your account and applies on every device you sign in on.",
  ),
  T(
    "User tab",
    "font_scale",
    "Text size",
    "Makes all text larger, from 100% to 200%, without breaking the layout.",
    "Every text size in the application scales together. The layout reflows at larger sizes, so nothing is clipped.",
  ),
  T(
    "User tab",
    "density",
    "Density",
    "How much space there is around items: compact, default or comfortable.",
    "Compact fits more rows on the screen; comfortable adds space, which some people find easier to read and to click.",
  ),
  T(
    "User tab",
    "reduced_motion",
    "Motion",
    "Whether panels and menus animate; follow the system, reduce or allow.",
    "Reduce motion turns animations off. Follow the system uses your operating system's reduced-motion setting.",
  ),
  T(
    "User tab",
    "toolbar_labels",
    "Toolbar labels",
    "Show the left toolbar's labels on hover only, or always.",
    "With labels always shown the toolbar is wider, and every icon has its name beside it.",
  ),
  T(
    "User tab",
    "locale",
    "Language",
    "The language of the application's own words. English is available now.",
    "This sets the interface language only; the language of captured documents is not changed. Translations of documents are a separate feature.",
  ),
  T(
    "User tab",
    "timezone",
    "Time zone",
    "The time zone used for every date and time shown to you.",
    "Dates and times are stored in UTC and shown in this zone.",
  ),
  T(
    "User tab",
    "session_idle_timeout_minutes",
    "Sign out after inactivity",
    "How long you can be inactive before you are signed out. You are signed out a minute early, to be safe, with a warning a minute before that.",
    "The administrator sets the longest time allowed. Shorter is safer on shared computers. Activity in any tab of the browser counts.",
  ),
  T(
    "User tab",
    "remember_me_default",
    "Keep me signed in by default",
    "Not in use yet: the sign-in page has no 'keep me signed in' box, so sessions always end when the browser closes or at their lifetime (BL-134).",
    "When ticked, your session survives closing the browser, up to the session's lifetime set by the administrator.",
  ),
  T(
    "User tab",
    "landing_view_id",
    "Landing view",
    "The saved view the map opens with: its period, colours and view.",
    "Choose one of your saved views, or one shared with you. If it is later removed or no longer shared, the map simply opens as usual.",
  ),
  T(
    "User tab",
    "sessions",
    "Active sessions",
    "Where you are signed in. You can sign out any other session from here.",
    "Signing out a session ends it at once: its next request is refused. Your current session is marked and cannot be ended from this list; use Sign out instead.",
  ),
];

const SETTINGS: Topic[] = [
  T(
    "Settings",
    "general.site_title",
    "Site title",
    "The application's name shown in the header, the browser tab and the sign-in page.",
  ),
  T(
    "Settings",
    "general.contact_email",
    "Contact email",
    "The address in the crawler's User-Agent and in footers, so publishers can reach you.",
    "Sites captured by regwatch see this address in each request. Use a team mailbox that is read.",
  ),
  T(
    "Settings",
    "branding.logo_ref",
    "Logo reference",
    "The stored logo file; set by uploading a logo on the Branding page, not by hand.",
  ),
  T(
    "Settings",
    "branding.company_name",
    "Company name",
    "Your organisation's full name, used in reports and the legal page.",
  ),
  T(
    "Settings",
    "branding.company_short_name",
    "Company short name",
    "A short form of the name for narrow places such as headers.",
  ),
  T(
    "Settings",
    "branding.company_address",
    "Company address",
    "The postal address shown in report footers and on the legal page.",
  ),
  T(
    "Settings",
    "branding.primary_color",
    "Primary colour",
    "The accent colour of the light theme, as #rrggbb; dark and high-contrast keep their own.",
    "Choose a colour with enough contrast against white text (4.5:1) for buttons to stay readable.",
  ),
  T(
    "Settings",
    "legal.page_markdown",
    "Legal page",
    "The text of the public legal page, written in Markdown.",
    "Raw HTML is not allowed; the text is sanitised before it is shown.",
  ),
  T(
    "Settings",
    "legal.required_markings",
    "Required markings",
    "A short marking shown in the footer and in report and email footers, such as a classification.",
  ),
  T(
    "Settings",
    "taxonomy.version",
    "Taxonomy version",
    "Counts changes to facets and terms; set by the system, not by hand.",
  ),
  T(
    "Settings",
    "map.default_period_days",
    "Default map period",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: the number of days the map shows when a user opens it without a landing view.",
  ),
  T(
    "Settings",
    "map.default_encoding",
    "Default map colours",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: what the map's colours mean by default: recency, number of changes or severity.",
  ),
  T(
    "Settings",
    "map.projection",
    "Map projection",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: the shape of the world map: Equal Earth (keeps areas in proportion) or Mercator.",
  ),
  T(
    "Settings",
    "capture.user_agent",
    "Crawler User-Agent",
    "How regwatch names itself to the sites it captures; the contact email is added to it.",
  ),
  T(
    "Settings",
    "capture.default_rate_per_minute",
    "Default capture rate",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: the most requests a source may make to one site each minute (30 by default), unless the source sets its own.",
    "Keep it low: publishers may block crawlers that request too often.",
  ),
  T(
    "Settings",
    "capture.max_body_bytes",
    "Largest captured document",
    "Captured documents larger than this are refused. A value below 64 KB or above 50 MB is treated as the nearest of the two.",
  ),
  T(
    "Settings",
    "capture.snapshot_versions_kept",
    "Snapshots kept",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: how many sanitised page snapshots are kept for each item; older ones are removed.",
  ),
  T(
    "Settings",
    "processing.change_threshold_pct",
    "Change threshold",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: how much of a document must change, in percent (5 by default), for a new version to count as a change.",
  ),
  T(
    "Settings",
    "processing.near_duplicate_ratio",
    "Near-duplicate ratio",
    "How similar two titles must be, from 80 to 100 (92 by default), for items to count as near duplicates; they must also share numbers and a jurisdiction and come from different sources.",
  ),
  T(
    "Settings",
    "classification.model_provider",
    "Classifier provider",
    "Which model service the optional classifier uses (none, Ollama or HTTP), when its feature flag is on.",
  ),
  T(
    "Settings",
    "classification.min_confidence",
    "Classifier minimum confidence",
    "Tags the classifier is less sure of than this are not applied.",
  ),
  T(
    "Settings",
    "translation.provider",
    "Translation provider",
    "Which service translates documents (none, Argos, LibreTranslate or HTTP), when translation is switched on.",
  ),
  T(
    "Settings",
    "translation.scope",
    "Translation scope",
    "What is translated: titles and summaries only (the default), or the full text.",
  ),
  T(
    "Settings",
    "translation.target_language",
    "Translation language",
    "The language documents are translated into.",
  ),
  T(
    "Settings",
    "translation.data_processing_basis",
    "Data-processing basis",
    "The recorded basis for sending text to a hosted translation service; it must be filled in before a hosted provider can be chosen.",
  ),
  T(
    "Settings",
    "search.page_size_max",
    "Largest search page",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: the most results one search page may return.",
  ),
  T(
    "Settings",
    "search.export_row_cap",
    "Export row limit",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: the most rows a CSV export may contain.",
  ),
  T(
    "Settings",
    "search.provider",
    "Internet search provider",
    "Which search service the search-query connector uses: none, SearXNG or HTTP.",
  ),
  T(
    "Settings",
    "outputs.allowed_recipient_domains",
    "Allowed email domains",
    "Reports may only be emailed to addresses in these domains, one per line; an empty list blocks all email.",
    "Subdomains count too: example.org also allows legal.example.org. So list your organisation's own domains only, never a shared provider's (such as a public mail service).",
    "Each recipient must be one plain address. Every message is audited with the recipient domains.",
  ),
  T(
    "Settings",
    "outputs.attachment_max_bytes",
    "Largest output file",
    "The largest PDF or CSV an output may produce, and so the largest email attachment (20 MB by default). A CSV that would be larger stops at a whole row, with a last line saying so.",
  ),
  T(
    "Settings",
    "outputs.artifact_retention_days",
    "Output retention",
    "How many days the files of outputs (PDFs and CSVs) are kept (90 by default). Older files are removed; the output stays in the history, without its download.",
  ),
  T(
    "Settings",
    "outputs.printer_networks",
    "Allowed printer networks",
    "The networks a printer's address must be in, one per line, such as 10.20.0.0/16. Empty by default, which allows no printer.",
    "Every address a printer's name resolves to must fall in one of these, and never on this computer, a link-local or multicast address, the server's own networks, or one of the application's own services. Printers use port 631 or 443 only. List your printers' subnets, as narrow as you can.",
  ),
  T(
    "Settings",
    "outputs.printer_plain_ipp",
    "Allow clear-text printers",
    "Allows printers at ipp:// addresses, which send documents unencrypted. Off by default; prefer ipps://.",
    "With it on, a document crosses the network readable by anyone on the path. A printer with a self-signed certificate can use ipps:// with its certificate's fingerprint instead.",
  ),
  T(
    "Settings",
    "outputs.rate_per_hour_per_user",
    "Outputs per hour",
    "How many reports or emails one user may produce each hour.",
  ),
  T(
    "Settings",
    "reports.default_page_size",
    "Report page size",
    "The paper size reports use unless a layout sets its own: A4 or Letter.",
  ),
  T(
    "Settings",
    "sessions.idle_timeout_max_minutes",
    "Longest idle time",
    "The longest a user may stay inactive before being signed out; users may choose shorter.",
  ),
  T(
    "Settings",
    "sessions.absolute_lifetime_hours",
    "Session lifetime",
    "However active, a session ends after this many hours and the user signs in again.",
  ),
  T(
    "Settings",
    "auth.lockout_threshold",
    "Lockout threshold",
    "Failed sign-ins within 15 minutes before the account is locked for a while; from 3 to 100.",
  ),
  T(
    "Settings",
    "auth.lockout_minutes",
    "Lockout length",
    "How long an account stays locked after too many failed sign-ins.",
  ),
  T(
    "Settings",
    "auth.password_min_length",
    "Shortest password",
    "The fewest characters a password may have.",
  ),
  T(
    "Settings",
    "auth.breach_check_enabled",
    "Breached-password check",
    "Refuse passwords known from public breaches, when the check is available.",
  ),
  T(
    "Settings",
    "retention.audit_days",
    "Audit retention",
    "Not in use yet: no part of the application reads this setting today (BL-134). Intended: how many days audit log entries are kept (730 by default).",
  ),
];

const FLAGS: Topic[] = [
  T(
    "Feature flags",
    "classification.model",
    "Model classifier",
    "Lets the optional model classifier tag items; rules always run.",
    "Off by default. When on, text is sent to the classifier provider set in Settings.",
  ),
  T(
    "Feature flags",
    "translation.enabled",
    "Translation",
    "Runs the translation step for items not in the target language.",
  ),
  T(
    "Feature flags",
    "search.internet",
    "Internet search connector",
    "Enables sources that discover documents through an internet search.",
  ),
  T(
    "Feature flags",
    "outputs.server_print",
    "Server printing",
    "Enables printing reports to network printers from the server.",
    "Printers are added under Settings, Printers, by an administrator; users with the print permission then choose one in New output. Each printer's address is checked against the allowed printer networks when it is saved and again before each job.",
  ),
];

const SOURCES: Topic[] = [
  T(
    "Sources",
    "name",
    "Source name",
    "A name people recognise, shown on items and in the sources table.",
  ),
  T(
    "Sources",
    "kind",
    "Connector kind",
    "How the source is read: a feed, a web page, a crawl, an API, a legislation service, a search or manual uploads.",
    "The kind decides which settings appear below. It cannot be changed later; create a new source instead.",
  ),
  T(
    "Sources",
    "credibility",
    "Credibility",
    "How authoritative the source is: official, secondary or news. It ranks duplicates and can be filtered.",
    "When the same document is captured from several sources, the most credible one owns the item. Search sources cannot be marked official.",
  ),
  T(
    "Sources",
    "schedule",
    "Schedule",
    "When the source is captured: every so many minutes, or on a cron schedule.",
  ),
  T(
    "Sources",
    "interval",
    "Minutes between runs",
    "How often the source is captured; at least 15 minutes, to be polite to the site.",
  ),
  T(
    "Sources",
    "cron",
    "Cron schedule",
    "Five fields: minute, hour, day of month, month, weekday. For example 0 6 * * 1-5 is 06:00 on weekdays.",
  ),
  T(
    "Sources",
    "timezone",
    "Schedule time zone",
    "The time zone the cron schedule is read in.",
  ),
  T(
    "Sources",
    "max_items",
    "Most items per run",
    "The most documents one run may take, so a burst never floods the pipeline.",
  ),
  T(
    "Sources",
    "rate",
    "Requests per minute",
    "The most requests one run makes to the site each minute.",
  ),
  T(
    "Sources",
    "enabled",
    "Enabled",
    "Whether the source is captured on its schedule. A disabled source keeps its items.",
  ),
  T(
    "Sources",
    "robots_override",
    "Override robots.txt",
    "Capture even where the site's robots.txt says no. Needs a written reason and the override permission, and is audited.",
    "Use this only with the site owner's permission or a clear legal basis, recorded in the reason.",
  ),
  T(
    "Sources",
    "respect_again",
    "Respect robots.txt again",
    "Ends an override, so captures follow the site's robots.txt again.",
  ),
];

export const TOPICS: readonly Topic[] = [
  ...ME,
  ...SETTINGS,
  ...FLAGS,
  ...SOURCES,
];
const BY_ID = new Map(TOPICS.map((t) => [t.id, t]));

/** The topic for an element: by full id, or by `area:key` as screens name their elements. */
export function topic(id: string): Topic | undefined {
  return BY_ID.get(id) ?? BY_ID.get(id.replace(/[^a-z0-9-]+/gi, "-"));
}

export const meTopic = (key: string) =>
  `me-${key.replace(/[^a-z0-9]+/gi, "-")}`;
export const settingTopic = (key: string) =>
  `setting-${key.replace(/[^a-z0-9]+/gi, "-")}`;
export const flagTopic = (key: string) =>
  `flag-${key.replace(/[^a-z0-9]+/gi, "-")}`;

export const sourceTopic = (key: string) =>
  `source-${key.replace(/[^a-z0-9]+/gi, "-")}`;
