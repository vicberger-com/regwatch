import { useQuery } from "@tanstack/react-query";
import { Link, useRouteContext } from "@tanstack/react-router";
import { useId, type ReactNode } from "react";

import { HelpTip } from "@/features/help/HelpTip";
import { FeedsEditor } from "./FeedsEditor";
import { InterestsEditor } from "./InterestsEditor";
import { meTopic } from "@/features/help/topics";
import { hasPermission, problemText } from "@/lib/auth/session";

import {
  myGroupsQuery,
  preferencesQuery,
  sessionsQuery,
  useRevokeSession,
  useSavePreferences,
  viewsQuery,
  type Preferences,
} from "./api";
import { formatDateTime } from "@/lib/time/format";

const TIMEZONES: readonly string[] = (() => {
  try {
    // "UTC" is the stored default but not in every browser's list (use testing U-M9-1).
    const zones = Intl.supportedValuesOf("timeZone");
    return zones.includes("UTC") ? zones : ["UTC", ...zones];
  } catch {
    return ["UTC"];
  }
})();

function Section(props: {
  id: string;
  title: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={props.id} className="mt-6 max-w-2xl">
      <div className="flex items-center gap-1">
        <h2 id={props.id} className="text-lg font-semibold">
          {props.title}
        </h2>
        {props.help && <HelpTip id={props.help} />}
      </div>
      <div className="mt-2 grid gap-3">{props.children}</div>
    </section>
  );
}

function Choice<K extends Exclude<keyof Preferences, "interests">>(props: {
  label: string;
  field: K;
  value: Preferences[K] | undefined;
  options: readonly { value: string; label: string }[];
  onSave: (changes: Partial<Preferences>) => void;
  parse?: (raw: string) => Preferences[K];
}) {
  const id = useId();
  return (
    <div className="flex flex-col text-sm">
      <span className="flex items-center gap-1">
        <label htmlFor={id}>{props.label}</label>
        <HelpTip id={meTopic(props.field)} />
      </span>
      <select
        id={id}
        className="mt-1 w-64 rounded border border-border bg-surface px-2 py-1"
        value={String(props.value ?? "")}
        onChange={(e) => {
          const raw = e.target.value;
          props.onSave({
            [props.field]: props.parse ? props.parse(raw) : raw,
          });
        }}
      >
        {props.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

const opts = (pairs: [string, string][]) =>
  pairs.map(([value, label]) => ({ value, label }));

/** `/me` (screens.md): profile, password, appearance, locale, session and defaults. */
export function MePage() {
  const { me } = useRouteContext({ from: "/authed" });
  const prefs = useQuery(preferencesQuery);
  const sessions = useQuery(sessionsQuery);
  const views = useQuery(viewsQuery);
  const save = useSavePreferences();
  const revoke = useRevokeSession();
  const groups = useQuery(myGroupsQuery);
  const p = prefs.data;
  const onSave = (changes: Partial<Preferences>) => {
    save.mutate(changes);
  };

  return (
    <>
      <h1 className="text-2xl font-semibold">User</h1>
      <p role="status" className="mt-2 text-sm text-text-muted">
        {save.isPending
          ? "Saving…"
          : save.isSuccess
            ? "Saved; it applies on every device you sign in on."
            : ""}
      </p>
      {(save.isError || prefs.isError) && (
        <p role="alert" className="text-critical">
          {problemText(
            save.error ?? prefs.error,
            "The preferences could not be saved.",
          )}
        </p>
      )}
      <Section id="profile" title="Profile">
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
          <dt className="text-text-muted">Name</dt>
          <dd>{me.display_name}</dd>
          <dt className="text-text-muted">Email</dt>
          <dd>{me.email}</dd>
          {groups.data && groups.data.length > 0 && (
            <>
              <dt className="text-text-muted">Groups</dt>
              <dd>{groups.data.map((g) => g.name).join(", ")}</dd>
            </>
          )}
        </dl>
        <p>
          <Link to="/change-password" className="text-accent underline">
            Change your password
          </Link>
        </p>
      </Section>
      {p && (
        <>
          {hasPermission(me, "items.read") && (
            <Section id="interests" title="Interests">
              {/* Keyed by the saved value, so a value the server dropped never lingers. */}
              <InterestsEditor
                key={JSON.stringify(p.interests ?? {})}
                saved={p.interests}
              />
            </Section>
          )}
          {hasPermission(me, "items.read") && (
            <Section id="feeds" title="Feeds" help={meTopic("feeds")}>
              <FeedsEditor />
            </Section>
          )}
          <Section id="appearance" title="Appearance">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={p.accessibility_preset}
                onChange={(e) => {
                  onSave({ accessibility_preset: e.target.checked });
                }}
              />
              Accessibility mode: high contrast, larger text and targets, labels
              always shown, less motion
            </label>
            <HelpTip id={meTopic("accessibility_preset")} />
            <Choice
              label="Theme"
              field="theme"
              value={p.theme}
              onSave={onSave}
              options={opts([
                ["system", "Follow the system"],
                ["light", "Light"],
                ["dark", "Dark"],
                ["high-contrast", "High contrast"],
              ])}
            />
            <Choice
              label="Text size"
              field="font_scale"
              value={p.font_scale}
              onSave={onSave}
              parse={(raw) => Number(raw) as Preferences["font_scale"]}
              options={[100, 112, 125, 150, 175, 200].map((n) => ({
                value: String(n),
                label: `${String(n)}%`,
              }))}
            />
            <Choice
              label="Density"
              field="density"
              value={p.density}
              onSave={onSave}
              options={opts([
                ["compact", "Compact"],
                ["default", "Default"],
                ["comfortable", "Comfortable"],
              ])}
            />
            <Choice
              label="Motion"
              field="reduced_motion"
              value={p.reduced_motion}
              onSave={onSave}
              options={opts([
                ["system", "Follow the system"],
                ["on", "Reduce motion"],
                ["off", "Allow motion"],
              ])}
            />
            <Choice
              label="Toolbar labels"
              field="toolbar_labels"
              value={p.toolbar_labels}
              onSave={onSave}
              options={opts([
                ["hover", "On hover"],
                ["always", "Always shown"],
              ])}
            />
          </Section>
          <Section id="locale" title="Language and time zone">
            <Choice
              label="Language"
              field="locale"
              value={p.locale}
              onSave={onSave}
              options={opts([["en", "English"]])}
            />
            <Choice
              label="Time zone"
              field="timezone"
              value={p.timezone}
              onSave={onSave}
              options={TIMEZONES.map((z) => ({ value: z, label: z }))}
            />
          </Section>
          <Section id="session" title="Session">
            <Choice
              label="Sign out after inactivity"
              field="session_idle_timeout_minutes"
              value={p.session_idle_timeout_minutes}
              onSave={onSave}
              parse={Number}
              options={[15, 20, 30, 60, 120, 240, 480]
                .filter(
                  (n) =>
                    n <= Math.max(480, p.session_idle_timeout_minutes ?? 0),
                )
                .map((n) => ({
                  value: String(n),
                  label: `${String(n)} minutes`,
                }))}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={p.remember_me_default}
                onChange={(e) => {
                  onSave({ remember_me_default: e.target.checked });
                }}
              />
              Keep me signed in by default
            </label>
            <HelpTip id={meTopic("remember_me_default")} />
          </Section>
          <Section id="defaults" title="Defaults">
            <div className="flex items-center gap-1 text-sm">
              <label htmlFor="landing-view">Landing view</label>
              <HelpTip id={meTopic("landing_view_id")} />
            </div>
            <div className="flex flex-col text-sm">
              <select
                id="landing-view"
                className="mt-1 w-64 rounded border border-border bg-surface px-2 py-1"
                value={p.landing_view_id ?? ""}
                onChange={(e) => {
                  onSave({ landing_view_id: e.target.value || null });
                }}
              >
                <option value="">The map</option>
                {(Array.isArray(views.data) ? views.data : []).map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </div>
          </Section>
        </>
      )}
      <Section id="sessions" title="Active sessions" help={meTopic("sessions")}>
        {revoke.isError && (
          <p role="alert" className="text-critical">
            {problemText(revoke.error, "That session could not be signed out.")}
          </p>
        )}
        {sessions.isError ? (
          <p role="alert" className="text-critical">
            {problemText(sessions.error, "The sessions could not be loaded.")}
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <caption className="mb-1 text-left text-text-muted">
              Where you are signed in
            </caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="py-1 pr-3">
                  Signed in
                </th>
                <th scope="col" className="py-1 pr-3">
                  Last seen
                </th>
                <th scope="col" className="py-1 pr-3">
                  Browser
                </th>
                <th scope="col" className="py-1">
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(sessions.data ?? []).map((s) => (
                <tr key={s.id} className="border-b border-border">
                  <td className="py-1 pr-3">
                    {s.created_at ? formatDateTime(s.created_at) : "—"}
                  </td>
                  <td className="py-1 pr-3">
                    {s.last_seen_at ? formatDateTime(s.last_seen_at) : "—"}
                  </td>
                  <td className="max-w-64 truncate py-1 pr-3">
                    {s.user_agent ?? "—"}
                  </td>
                  <td className="py-1">
                    {s.current ? (
                      <span className="text-text-muted">This session</span>
                    ) : (
                      <button
                        type="button"
                        className="text-accent underline"
                        disabled={revoke.isPending}
                        onClick={() => {
                          if (s.id) revoke.mutate(s.id);
                        }}
                      >
                        Sign out this session
                        <span className="sr-only">
                          {" "}
                          (signed in{" "}
                          {s.created_at
                            ? formatDateTime(s.created_at)
                            : ""}, {s.user_agent ?? "unknown browser"})
                        </span>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </>
  );
}
