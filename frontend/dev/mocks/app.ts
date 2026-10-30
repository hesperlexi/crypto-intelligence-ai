// DEV PREVIEW ONLY. Stand-in for "firebase/app" and the lazily loaded Firebase modules.
export const initializeApp = (cfg: any) => ({ options: cfg });
export const getAnalytics = () => null;
export const isSupported = async () => false;
export const initializeAppCheck = () => null;
export class ReCaptchaV3Provider { constructor(_k: string) {} }
export const getMessaging = () => null;
export const getToken = async () => "";
export const deleteToken = async () => true;
