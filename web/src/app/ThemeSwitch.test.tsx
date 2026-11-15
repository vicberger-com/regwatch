import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { THEME_STORAGE_KEY } from "./theme";
import { ThemeSwitch } from "./ThemeSwitch";

const html = () => document.documentElement;

describe("ThemeSwitch", () => {
  it("cycles light, dark and high contrast without a reload and persists each choice", async () => {
    const user = userEvent.setup();
    render(<ThemeSwitch />);
    const button = screen.getByRole("button", { name: /theme: light/i });

    await user.click(button);
    expect(html().dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(button).toHaveTextContent("Theme: Dark");

    await user.click(button);
    expect(html().dataset.theme).toBe("high-contrast");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("high-contrast");
    expect(button).toHaveAccessibleName(
      "Theme: High contrast. Switch to Light",
    );

    await user.click(button);
    expect(html().dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    // Same element throughout: the page was never reloaded or re-mounted.
    expect(screen.getByRole("button")).toBe(button);
  });

  it("starts from the stored theme", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "high-contrast");
    render(<ThemeSwitch />);
    expect(screen.getByRole("button")).toHaveTextContent(
      "Theme: High contrast",
    );
  });

  it("works from the keyboard", async () => {
    const user = userEvent.setup();
    render(<ThemeSwitch />);
    await user.tab();
    expect(screen.getByRole("button")).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(html().dataset.theme).toBe("dark");
  });
});
