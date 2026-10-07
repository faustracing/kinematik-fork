import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DevHarness } from "./DevHarness";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DevHarness />
  </StrictMode>,
);
