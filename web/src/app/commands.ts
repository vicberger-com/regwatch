/**
 * The toolbar command registry (M6 Interfaces): modules register commands, and the shell shows
 * the ones the signed-in user may use. A command either navigates (`to`) or runs a handler
 * (`run`); the API enforces every permission again, so hiding a command is convenience, never
 * the control.
 */
import type { LucideIcon } from "lucide-react";
import { Map, Settings } from "lucide-react";

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
  registry.set(command.id, command);
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

/** Every admin permission that opens an area of the settings home. */
export const ADMIN_PERMISSIONS = [
  "users.manage",
  "roles.manage",
  "settings.manage",
  "audit.read",
  "taxonomy.read",
  "sources.read",
] as const;

/**
 * The shell's own commands. Items (20), Reports (30), Outputs (40) and User (50) register
 * theirs with their screens, so the rail never links to a page that does not exist yet.
 */
export function registerShellCommands(): void {
  registerCommand({
    id: "nav.map",
    label: "Map",
    icon: Map,
    to: "/",
    order: 10,
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
