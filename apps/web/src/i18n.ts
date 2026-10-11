import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

export const resources = {
  zh: {
    translation: {
      app: {
        tagline: "桌面工作伙伴",
        langLabel: "EN",
      },
      nav: {
        home: "主页",
        chat: "对话",
        project: "项目",
        reminders: "提醒",
        character: "角色卡",
        memory: "记忆",
        kb: "知识库",
        agents: "我的智能体",
        extensions: "技能扩展",
        settings: "设置",
        about: "关于",
      },
      service: {
        running: "本地服务运行中",
        stopped: "本地服务已退出",
        offline: "本地服务离线",
      },
    },
  },
  en: {
    translation: {
      app: {
        tagline: "Your Desktop Workmate",
        langLabel: "中",
      },
      nav: {
        home: "Home",
        chat: "Chat",
        project: "Projects",
        reminders: "Reminders",
        character: "Character",
        memory: "Memory",
        kb: "Knowledge Base",
        agents: "My Agents",
        extensions: "Extensions",
        settings: "Settings",
        about: "About",
      },
      service: {
        running: "Local service running",
        stopped: "Local service stopped",
        offline: "Local service offline",
      },
    },
  },
} as const;

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "zh",
    supportedLngs: ["zh", "en"],
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "qiling.lang",
    },
    interpolation: { escapeValue: false },
  });

export default i18n;
