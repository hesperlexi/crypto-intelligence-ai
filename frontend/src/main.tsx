import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppearanceProvider } from "./lib/appearance";
import { ModeProvider } from "./lib/mode";
import { startUpdater } from "./lib/updater";
import "./index.css";
import { CosmicBackdrop } from "./components/Xeno";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <ModeProvider>
        <BrowserRouter>
          <CosmicBackdrop />
          <App />
        </BrowserRouter>
      </ModeProvider>
    </AppearanceProvider>
  </React.StrictMode>,
);

// PWA: service worker + automatic updates after every deploy (production builds only)
startUpdater();
