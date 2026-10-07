import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { StreamlitApp } from "./StreamlitApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StreamlitApp />
  </StrictMode>,
);
