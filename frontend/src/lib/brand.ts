// Brand values shared with the engine (backend app/brand.py holds the same values; see docs/v1-contract.md).
import { APP_VERSION } from "./version";

export const BRAND = {
  name: "Crypto Intelligence AI",
  url: "https://www.cryptointelai.com",
  supportEmail: "support@cryptointelai.com",
  tagline: "AI market analysis for crypto traders",
  disclaimer: "Analysis only, not financial advice. No guaranteed profits.",
  version: APP_VERSION,
  telegram: "https://t.me/crypappai",
} as const;

/** The site address without the scheme, for printed text (images, captions, footers). */
export const SITE_HOST = BRAND.url.replace(/^https?:\/\//, "");

/** The old Firebase address: still live for the Android app and existing links (never retire it). */
export const LEGACY_HOST = "crypapp-6a9b9.web.app";

/** Footer line, exactly as in the contract. */
export const footerText = (version: string = BRAND.version) =>
  `${BRAND.name} v${version} · ${SITE_HOST} · ${BRAND.supportEmail} · Analysis only, not financial advice.`;
