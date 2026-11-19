import { Map } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";

import type { Me } from "@/lib/auth/session";
import { ADMIN } from "@/test/api";

import {
  commandsFor,
  railCommands,
  registerCommand,
  registerShellCommands,
  resetCommands,
} from "./commands";

const withPermissions = (permissions: string[]): Me =>
  ({ ...ADMIN, permissions }) as Me;

afterEach(resetCommands);

describe("command registry", () => {
  it("shows only the commands a user may use, in rail order", () => {
    registerShellCommands();
    registerCommand({
      id: "x.print",
      label: "Print",
      icon: Map,
      run: () => undefined,
      permission: "items.read",
    });
    expect(railCommands(withPermissions([]))).toEqual([]);
    expect(
      railCommands(withPermissions(["audit.read"])).map((c) => c.id),
    ).toEqual(["nav.settings"]);
    expect(
      commandsFor(withPermissions(["items.read"])).map((c) => c.id),
    ).toEqual(["nav.map", "nav.items", "x.print"]);
    expect(commandsFor(null)).toEqual([]);
  });

  it("needs exactly one of a route and a handler", () => {
    expect(() => {
      registerCommand({ id: "bad", label: "Bad", icon: Map });
    }).toThrow(/exactly one/);
    expect(() => {
      registerCommand({
        id: "bad",
        label: "Bad",
        icon: Map,
        to: "/",
        run: () => undefined,
      });
    }).toThrow(/exactly one/);
  });

  it("refuses a different command under a taken id", () => {
    registerShellCommands();
    expect(() => {
      registerCommand({
        id: "nav.settings",
        label: "Settings",
        icon: Map,
        to: "/admin",
        order: 60,
      });
    }).toThrow(/already registered/);
  });

  it("registering the shell commands again is harmless", () => {
    registerShellCommands();
    registerShellCommands();
    expect(
      commandsFor(withPermissions(["users.manage", "items.read"])),
    ).toHaveLength(3);
  });
});
