/**
 * GitReview AI — Popup entry point
 * Mounts the React app into the #root div in popup.html.
 */

import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root container not found in popup.html");
}

createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
