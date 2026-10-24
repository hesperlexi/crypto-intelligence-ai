declare const __APP_VERSION__: string;
declare const __BUILD_ID__: string;

export const APP_VERSION: string = typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "1.2";
export const BUILD_ID: string = typeof __BUILD_ID__ !== "undefined" ? __BUILD_ID__ : "dev";
export const COPYRIGHT = "© 2026 Hesper. All rights reserved.";
