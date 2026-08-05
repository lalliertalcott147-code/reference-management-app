import { lazy, Suspense, useEffect, useState } from "react";
import {
  fetchHealth,
  fetchSettings,
  type HealthResponse,
  type SettingsResponse,
  updateSettings,
} from "./api";
import { startLifecycleHeartbeat } from "./lifecycle";
import { ImportPage } from "./pages/ImportPage";
import { ProfileAvatar } from "./components/ProfileAvatar";
import { HomePage } from "./pages/HomePage";
import { JournalsPage } from "./pages/JournalsPage";
import { LibraryPage } from "./pages/LibraryPage";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import "./styles.css";

const PdfReaderPage = lazy(async () => ({
  default: (await import("./pages/PdfReaderPage")).PdfReaderPage,
}));

type Page = "home" | "search" | "journals" | "library" | "settings" | "import" | "reader";
type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse; settings: SettingsResponse }
  | { kind: "error"; message: string };

const navItems: { page: Page; label: string; icon: string }[] = [
  { page: "home", label: "首页", icon: "⌂" },
  { page: "search", label: "检索", icon: "⌕" },
  { page: "journals", label: "期刊", icon: "◫" },
  { page: "library", label: "知识库", icon: "▤" },
  { page: "settings", label: "设置", icon: "⚙" },
];

function pageFromHash(): Page {
  const page = location.hash.replace("#", "").split("?", 1)[0] as Page;
  return ["home", "search", "journals", "library", "settings", "import", "reader"].includes(page) ? page : "home";
}

export function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [page, setPage] = useState<Page>(pageFromHash);

  useEffect(() => startLifecycleHeartbeat(), []);
  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([fetchHealth(controller.signal), fetchSettings(controller.signal)])
      .then(([health, settings]) => setState({ kind: "ready", health, settings }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ kind: "error", message: error instanceof Error ? error.message : "未知错误" });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") return <main className="boot-screen" role="status"><span className="brand-mark">Cu</span><p>正在启动本地文献工作台…</p></main>;
  if (state.kind === "error") return <main className="boot-screen"><h1>本地服务连接失败</h1><p role="alert">{state.message}</p><button className="primary-button" type="button" onClick={() => location.reload()}>重新连接</button></main>;

  const setSettings = (settings: SettingsResponse) => setState({ ...state, settings });
  if (page === "reader") return <Suspense fallback={<main className="boot-screen">正在加载本地阅读器…</main>}><PdfReaderPage /></Suspense>;
  return <main className="shell"><aside className="sidebar" aria-label="应用侧栏"><div className="brand"><ProfileAvatar avatarUrl={state.settings.avatar_url} onUploaded={(avatarUrl) => setSettings({ ...state.settings, avatar_url: avatarUrl })} /><a className="brand-copy" href="#home"><strong>{state.settings.display_name}</strong><small>Catalyst Library</small></a></div><nav aria-label="主导航">{navItems.map((item) => <a key={item.page} className={page === item.page ? "active" : ""} href={`#${item.page}`}><span>{item.icon}</span>{item.label}</a>)}</nav><div className="local-badge"><span className="status-dot" /><span>仅本机运行<small>数据保存在此电脑</small></span></div></aside><section className="content">{page === "home" && <HomePage health={state.health} />}{page === "search" && <SearchPage />}{page === "import" && <ImportPage />}{page === "journals" && <JournalsPage />}{page === "library" && <LibraryPage />}{page === "settings" && <SettingsPage settings={state.settings} onChange={setSettings} />}</section>{!state.settings.onboarding_complete && <div className="modal-backdrop"><section className="onboarding" role="dialog" aria-modal="true" aria-labelledby="welcome-title"><span className="brand-mark">Cu</span><p className="eyebrow">欢迎使用</p><h1 id="welcome-title">这是你的本地文献工作台</h1><ul><li>数据永久保存在当前电脑</li><li>只调用你配置的免费外部服务</li><li>不会模拟学校登录或抓取登录网页</li></ul><button className="primary-button" type="button" onClick={() => { void updateSettings({ onboarding_complete: true }).then(setSettings); }}>知道了，开始使用</button></section></div>}</main>;
}
