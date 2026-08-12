import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./themes.css";

const requestedTheme = new URLSearchParams(window.location.search).get("theme");
document.documentElement.dataset.theme = requestedTheme === "glass" ? "glass" : "vellum";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
