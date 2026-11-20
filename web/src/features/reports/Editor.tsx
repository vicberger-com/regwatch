/**
 * The Puck editor (lazy-loaded chunk; ADR-0005: pinned 0.24.0, `no-external.css`) with the
 * project's keyboard layer (BL-16; WCAG 2.1.1 and 2.5.7), on Puck's public API only:
 * - Enter on a focused canvas item selects it (Puck itself only reacts to the pointer);
 * - the selected item's action bar has Move up and Move down;
 * - "Add a component" (outside the drag-only drawer) inserts after the selection or at the end;
 * - every change is announced in a polite live region;
 * - Puck's loading spinner, a `<span aria-label>` with no role, is given `role="status"`.
 */
import "@puckeditor/core/no-external.css";

import { ActionBar, Puck, useGetPuck, type Data } from "@puckeditor/core";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { ReportField } from "./api";
import { reportConfig } from "./puckConfig";

const ROOT_ZONE = "root:default-zone";
const Announce = createContext<(message: string) => void>(() => undefined);

function itemsIn(data: Data, zone: string): unknown[] {
  return zone === ROOT_ZONE ? data.content : (data.zones?.[zone] ?? []);
}

function MovingActionBar(props: {
  label?: string;
  children: ReactNode;
  parentAction: ReactNode;
  dragHandle?: ReactNode;
}) {
  const getPuck = useGetPuck();
  const say = useContext(Announce);
  const move = (delta: number) => {
    const { appState, dispatch } = getPuck();
    const selected = appState.ui.itemSelector;
    if (!selected) return;
    const zone = selected.zone ?? ROOT_ZONE;
    const count = itemsIn(appState.data, zone).length;
    const to = selected.index + delta;
    if (to < 0 || to >= count) {
      say(delta < 0 ? "Already first." : "Already last.");
      return;
    }
    dispatch({
      type: "move",
      sourceIndex: selected.index,
      sourceZone: zone,
      destinationIndex: to,
      destinationZone: zone,
    });
    dispatch({ type: "setUi", ui: { itemSelector: { index: to, zone } } });
    say(`Moved to position ${String(to + 1)} of ${String(count)}.`);
  };
  return (
    <ActionBar>
      <ActionBar.Group>
        {props.parentAction}
        {props.label && <ActionBar.Label label={props.label} />}
      </ActionBar.Group>
      <ActionBar.Group>
        <ActionBar.Action
          label="Move up"
          onClick={() => {
            move(-1);
          }}
        >
          <span aria-hidden="true">↑</span>
        </ActionBar.Action>
        <ActionBar.Action
          label="Move down"
          onClick={() => {
            move(1);
          }}
        >
          <span aria-hidden="true">↓</span>
        </ActionBar.Action>
        {props.children}
      </ActionBar.Group>
      {props.dragHandle && (
        <ActionBar.Group>{props.dragHandle}</ActionBar.Group>
      )}
    </ActionBar>
  );
}

/** In Puck's header: "Add a component", keyboard selection, and the live region. */
function KeyboardTools(props: {
  types: { name: string; label: string }[];
  children: ReactNode;
}) {
  const id = useId();
  const getPuck = useGetPuck();
  const [type, setType] = useState(props.types[0]?.name ?? "");
  const box = useRef<HTMLDivElement>(null);
  const say = useContext(Announce);

  useEffect(() => {
    const root = box.current?.closest("[data-report-editor]");
    if (!root) return;
    const onKey = (e: Event) => {
      const event = e as KeyboardEvent;
      if (event.key !== "Enter") return;
      const item = (event.target as Element | null)?.closest(
        "[data-puck-component]",
      );
      const itemId = item?.getAttribute("data-puck-component");
      if (!itemId) return;
      const { getSelectorForId, dispatch } = getPuck();
      const selector = getSelectorForId(itemId);
      if (!selector) return;
      event.preventDefault();
      dispatch({ type: "setUi", ui: { itemSelector: selector } });
      say(
        "Selected. Its fields are in the panel; Move up and Move down are on the item.",
      );
    };
    root.addEventListener("keydown", onKey);
    // Puck's spinner: an aria-label needs a role (axe aria-prohibited-attr; upstream #1807).
    const label = () => {
      root.querySelectorAll("span[aria-label]:not([role])").forEach((s) => {
        if (s.className.includes("Loader")) s.setAttribute("role", "status");
      });
    };
    label();
    const watch = new MutationObserver(label);
    watch.observe(root, { childList: true, subtree: true });
    return () => {
      root.removeEventListener("keydown", onKey);
      watch.disconnect();
    };
  }, [getPuck, say]);

  const add = () => {
    const { appState, dispatch } = getPuck();
    const selected = appState.ui.itemSelector;
    const zone = selected?.zone ?? ROOT_ZONE;
    const at = selected
      ? selected.index + 1
      : itemsIn(appState.data, zone).length;
    dispatch({
      type: "insert",
      componentType: type,
      destinationIndex: at,
      destinationZone: zone,
    });
    dispatch({ type: "setUi", ui: { itemSelector: { index: at, zone } } });
    const label = props.types.find((t) => t.name === type)?.label ?? type;
    say(`${label} added at position ${String(at + 1)} and selected.`);
  };

  return (
    <div ref={box} className="flex flex-wrap items-center gap-2">
      <label htmlFor={`${id}-type`} className="text-sm">
        Add a component
      </label>
      <select
        id={`${id}-type`}
        value={type}
        className="rounded border border-border px-2 py-1 text-sm"
        onChange={(e) => {
          setType(e.target.value);
        }}
      >
        {props.types.map((t) => (
          <option key={t.name} value={t.name}>
            {t.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="rounded border border-border px-2 py-1 text-sm"
        onClick={add}
      >
        Add
      </button>
      {props.children}
    </div>
  );
}

export default function Editor(props: {
  fields: ReportField[];
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
}) {
  const config = useMemo(() => reportConfig(props.fields), [props.fields]);
  const [message, setMessage] = useState("");
  const say = useMemo(
    () => (m: string) => {
      setMessage(""); // cleared first, so a repeated message is announced again
      window.setTimeout(() => {
        setMessage(m);
      }, 30);
    },
    [],
  );
  const types = Object.entries(config.components).map(([name, c]) => ({
    name,
    label: c.label ?? name,
  }));
  return (
    <Announce.Provider value={say}>
      <div
        data-report-editor
        className="min-h-[70vh] rounded border border-border"
      >
        <span role="status" aria-live="polite" className="sr-only">
          {message}
        </span>
        <Puck
          config={config}
          data={props.data}
          onChange={(data) => {
            props.onChange(data);
          }}
          iframe={{ enabled: false }}
          headerTitle="Report layout"
          overrides={{
            actionBar: MovingActionBar,
            headerActions: ({ children }) => (
              <KeyboardTools types={types}>{children}</KeyboardTools>
            ),
          }}
        />
      </div>
    </Announce.Provider>
  );
}
