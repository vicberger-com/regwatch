import {
  applyTheme,
  isTheme,
  nextTheme,
  readStoredTheme,
  THEME_STORAGE_KEY,
} from "./theme";

function brokenStorage(): Storage {
  const fail = () => {
    throw new DOMException("blocked", "SecurityError");
  };
  return {
    getItem: fail,
    setItem: fail,
    removeItem: fail,
    clear: fail,
    key: fail,
    length: 0,
  };
}

describe("theme helpers", () => {
  it("cycles in contract order", () => {
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("high-contrast");
    expect(nextTheme("high-contrast")).toBe("light");
  });

  it("recognises only the three themes", () => {
    expect(isTheme("dark")).toBe(true);
    expect(isTheme("sepia")).toBe(false);
    expect(isTheme(null)).toBe(false);
  });

  it("falls back to light for unknown, missing or blocked storage", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredTheme()).toBe("light");
    expect(readStoredTheme(null)).toBe("light");
    expect(readStoredTheme(brokenStorage())).toBe("light");
  });

  it("still applies the theme when storage is blocked", () => {
    applyTheme("dark", document.documentElement, brokenStorage());
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
