import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createAppRouter } from "@/app/router";
import { applyTheme, readStoredTheme } from "@/app/theme";

import "@/styles/index.css";

applyTheme(readStoredTheme());

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
