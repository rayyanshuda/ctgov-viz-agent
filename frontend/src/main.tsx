// Starts the app. Three providers wrap everything:
//   QueryClientProvider - React Query, which runs and caches the API calls
//   BrowserRouter       - lets the URL decide which page shows (/, /charts, /c/<id>)
//   AskProvider         - the shared "ask a question" state (see AskContext.tsx)

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AskProvider } from "./AskContext";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AskProvider>
          <App />
        </AskProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
