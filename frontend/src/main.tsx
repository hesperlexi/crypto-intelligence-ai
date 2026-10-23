import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppearanceProvider } from "./lib/appearance";
import { startUpdater } from "./lib/updater";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AppearanceProvider>
  </React.StrictMode>,
);

// PWA: service worker + automatic updates after every deploy (production builds only)
startUpdater();
