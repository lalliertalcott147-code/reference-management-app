import { useEffect, useState } from "react";
import {
  type AppAlert,
  type HealthResponse,
  type Recommendation,
  fetchAlerts,
  fetchRecommendations,
  markAllAlertsRead,
} from "../api";

export function HomePage({ health }: { health: HealthResponse }) {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [alerts, setAlerts] = useState<AppAlert[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void Promise.all([fetchRecommendations(), fetchAlerts()])
      .then(([nextRecommendations, nextAlerts]) => {
        setRecommendations(nextRecommendations);
        setAlerts(nextAlerts);
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "读取本地推荐失败");
      });
  }, []);

  async function clearUnread() {
    await markAllAlertsRead();
    setAlerts((current) => current.map((item) => ({ ...item, is_read: true })));
  }

  return <div className="page home-page">
    <section className="hero compact-hero">
      <div>
        <p className="eyebrow">本地文献工作台</p>
        <h1>把检索、阅读和笔记<br />留在自己的电脑里</h1>
        <p className="hero-copy">以 Web of Science 为主通道，开放来源补全摘要；PDF、译文、收藏和笔记只保存在本机。</p>
        <div className="hero-actions"><a className="primary-button" href="#search">开始检索</a><a className="secondary-button" href="#import">导入 WoS 记录</a></div>
      </div>
      <div className="molecule-card" aria-hidden="true"><span className="atom atom-a" /><span className="atom atom-b" /><span className="atom atom-c" /><i /><b>Cu</b></div>
    </section>

    <section className="home-section" aria-labelledby="recommendation-title">
      <div className="section-heading"><div><p className="eyebrow">透明规则</p><h2 id="recommendation-title">为你推荐</h2></div><a href="#settings">调整研究偏好</a></div>
      {recommendations.length === 0
        ? <div className="empty-inline">设置研究主题，或运行保存检索后，这里会按真实命中原因推荐文献。</div>
        : <div className="recommendation-grid">{recommendations.map((item) => <article key={item.paper_id}>
          <span className="score-pill">匹配分 {item.score}</span>
          <h3>{item.title}</h3>
          <p>{item.journal ?? "期刊待补充"} · {item.year ?? "年份待补充"}</p>
          <ul>{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          <a href="#library">在知识库中查看</a>
        </article>)}</div>}
    </section>

    <section className="home-section" aria-labelledby="alert-title">
      <div className="section-heading"><div><p className="eyebrow">仅 App 内</p><h2 id="alert-title">提醒中心</h2></div>{alerts.some((item) => !item.is_read) && <button type="button" onClick={() => void clearUnread()}>全部已读</button>}</div>
      {alerts.length === 0 ? <div className="empty-inline">暂无更新提醒。自动检查只在 App 打开期间运行。</div> : <div className="alert-list">{alerts.map((item) => <article className={item.is_read ? "read" : ""} key={item.id}><span>{item.kind === "quota" ? "额度" : item.kind === "error" ? "异常" : "更新"}</span><div><strong>{item.title}</strong><p>{item.message}</p><small>{new Date(item.created_at).toLocaleString()}</small></div></article>)}</div>}
    </section>
    {message && <div className="notice error" role="alert">{message}</div>}
    <div className="connection-bar" role="status"><span className="status-dot" />本地服务已连接 · 版本 {health.version} · 数据库 {health.database === "ready" ? "正常" : "未初始化"}</div>
  </div>;
}
