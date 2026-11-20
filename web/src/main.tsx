import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createAppRouter } from "@/app/router";
import { applyAppearance, readStoredAppearance } from "@/app/appearance";
import { applyTheme, readStoredTheme } from "@/app/theme";

import "@/styles/fonts.css";
import "@/styles/index.css";

// Before the first render: the last appearance seen, so a reload never flashes (M9).
const stored = readStoredAppearance();
if (stored) applyAppearance(stored);
else applyTheme(readStoredTheme());

const container = document.getElementById("root");
if (!container) throw new Error("#root element missing from index.html");

const queryClient = new QueryClient();
const router = createAppRouter(queryClient);

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
