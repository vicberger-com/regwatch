import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppShell } from "@/app/AppShell";
import { applyTheme, readStoredTheme } from "@/app/theme";

import "@/styles/index.css";

applyTheme(readStoredTheme());

const container = document.getElementById("root");
if (!container) throw new Error("#root element missing from index.html");

createRoot(container).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
);
