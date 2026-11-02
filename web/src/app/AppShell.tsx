import { ThemeSwitch } from "./ThemeSwitch";

export function AppShell() {
  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-surface focus:p-2"
      >
        Skip to main content
      </a>
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-2">
        <span className="text-lg font-semibold">regwatch</span>
        <ThemeSwitch />
      </header>
      <main id="main" className="flex-1 p-6">
        <h1 className="text-2xl font-semibold">Regulatory monitor</h1>
        <p className="mt-2 text-text-muted">
          Platform scaffold. Screens arrive with their modules.
        </p>
      </main>
    </div>
  );
}
