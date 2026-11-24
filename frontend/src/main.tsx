import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppearanceProvider } from "./lib/appearance";
import { ModeProvider } from "./lib/mode";
import { startUpdater } from "./lib/updater";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-700.css";
import "./index.css";
import "./styles/observatory.css";
import "./styles/v3.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <ModeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ModeProvider>
    </AppearanceProvider>
  </React.StrictMode>,
);

// PWA: service worker + automatic updates after every deploy (production builds only)
startUpdater();
