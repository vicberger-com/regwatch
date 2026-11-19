/**
 * The toolbar command registry (M6 Interfaces): modules register commands, and the shell shows
 * the ones the signed-in user may use. A command either navigates (`to`) or runs a handler
 * (`run`); the API enforces every permission again, so hiding a command is convenience, never
 * the control.
 */
import type { LucideIcon } from "lucide-react";
import { List, Map, Settings } from "lucide-react";

import { hasPermission } from "@/lib/auth/session";
import type { Me } from "@/lib/auth/session";

export interface Command {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Permission key the command needs; none means every signed-in user. */
  permission?: string;
  /** Any one of these permissions is enough (the settings home spans several admin areas). */
  anyPermission?: readonly string[];
  shortcut?: string;
  /** A route path to navigate to; the left rail shows navigation commands in `order`. */
  to?: string;
  run?: () => void;
  /** Position in the left rail (screens.md: Map, Items, Reports, Outputs, User, Settings). */
  order?: number;
}

const registry = new globalThis.Map<string, Command>();

export function registerCommand(command: Command): void {
  if (!command.to === !command.run) {
    throw new Error(
      `command ${command.id}: give exactly one of "to" and "run"`,
    );
  }
  const taken = registry.get(command.id);
  if (taken && taken !== command && !sameCommand(taken, command)) {
    throw new Error(`command ${command.id} is already registered`);
  }
  registry.set(command.id, command);
}

function sameCommand(a: Command, b: Command): boolean {
  return (
    a.label === b.label &&
    a.to === b.to &&
    a.run === b.run &&
    a.shortcut === b.shortcut &&
    a.permission === b.permission &&
    String(a.anyPermission) === String(b.anyPermission) &&
    a.order === b.order &&
    a.icon === b.icon
  );
}

export function allowed(command: Command, me: Me | null | undefined): boolean {
  if (command.permission && !hasPermission(me, command.permission))
    return false;
  if (
    command.anyPermission &&
    !command.anyPermission.some((p) => hasPermission(me, p))
  ) {
    return false;
  }
  return true;
}

/** The commands ``me`` may use, rail order first, then by label. */
export function commandsFor(me: Me | null | undefined): Command[] {
  return [...registry.values()]
    .filter((c) => allowed(c, me))
    .sort(
      (a, b) =>
        (a.order ?? 1000) - (b.order ?? 1000) || a.label.localeCompare(b.label),
    );
}

export function railCommands(me: Me | null | undefined): Command[] {
  return commandsFor(me).filter(
    (c) => c.to !== undefined && c.order !== undefined,
  );
}

/** The admin areas of the settings home (screens.md `/admin`), each with the permission its
 * route checks. */
export const ADMIN_AREAS = [
  {
    to: "/admin/users",
    title: "Users",
    text: "Accounts, roles and temporary passwords.",
    permission: "users.manage",
  },
  {
    to: "/admin/roles",
    title: "Roles",
    text: "Permissions grouped by module.",
    permission: "roles.manage",
  },
  {
    to: "/admin/settings",
    title: "Settings",
    text: "Application settings by area.",
    permission: "settings.manage",
  },
  {
    to: "/admin/branding",
    title: "Branding and legal",
    text: "Logo, title, colour and the legal page.",
    permission: "settings.manage",
  },
  {
    to: "/admin/flags",
    title: "Feature flags",
    text: "Optional features and providers.",
    permission: "settings.manage",
  },
  {
    to: "/admin/audit",
    title: "Audit log",
    text: "Who changed what, with before and after.",
    permission: "audit.read",
  },
  {
    to: "/admin/taxonomy",
    title: "Taxonomy",
    text: "Facets, terms and match rules.",
    permission: "taxonomy.read",
  },
  {
    to: "/admin/jurisdictions",
    title: "Jurisdictions",
    text: "Countries, regions and bodies.",
    permission: "taxonomy.read",
  },
  {
    to: "/admin/sources",
    title: "Sources",
    text: "Capture sources, schedules and runs.",
    permission: "sources.read",
  },
] as const;

/** Every admin permission that opens an area of the settings home. */
export const ADMIN_PERMISSIONS = [
  ...new Set(ADMIN_AREAS.map((a) => a.permission)),
];

/**
 * The shell's own commands. Reports (30), Outputs (40) and User (50) register theirs with
 * their screens, so the rail never links to a page that does not exist yet.
 */
export function registerShellCommands(): void {
  registerCommand({
    id: "nav.map",
    label: "Map",
    icon: Map,
    to: "/",
    order: 10,
    permission: "items.read",
  });
  registerCommand({
    id: "nav.items",
    label: "Items",
    icon: List,
    to: "/items",
    order: 20,
    permission: "items.read",
  });
  registerCommand({
    id: "nav.settings",
    label: "Settings",
    icon: Settings,
    to: "/admin",
    order: 60,
    anyPermission: ADMIN_PERMISSIONS,
  });
}

/** Tests only: start from an empty registry. */
export function resetCommands(): void {
  registry.clear();
}
