import { type FormEvent, useEffect, useState } from "react";
import {
  type JournalPaper,
  type JournalSubscription,
  type SavedSearch,
  deleteSavedSearch,
  fetchJournalPapers,
  fetchJournalSubscriptions,
  fetchSavedSearches,
  followJournal,
  runJournal,
  runSavedSearch,
  setJournalEnabled,
  setSavedSearchEnabled,
} from "../api";

function timeLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "尚未检查";
}

export function JournalsPage() {
  const [journals, setJournals] = useState<JournalSubscription[]>([]);
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [selectedJournal, setSelectedJournal] = useState<JournalSubscription | null>(null);
  const [latestPapers, setLatestPapers] = useState<JournalPaper[]>([]);
  const [refreshingJournal, setRefreshingJournal] = useState<number | null>(null);

  async function reload() {
    const [nextJournals, nextSearches] = await Promise.all([
      fetchJournalSubscriptions(), fetchSavedSearches(),
    ]);
    setJournals(nextJournals);
    setSearches(nextSearches);
    setSelectedJournal((current) => current
      ? nextJournals.find((journal) => journal.id === current.id) ?? current
      : null);
  }

  useEffect(() => {
    void Promise.all([fetchJournalSubscriptions(), fetchSavedSearches()])
      .then(([nextJournals, nextSearches]) => {
        setJournals(nextJournals);
        setSearches(nextSearches);
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "读取关注更新失败");
      });
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    await followJournal(title);
    setTitle("");
    setMessage("期刊已关注；自动检查仅在 App 打开时运行。");
    await reload();
  }

  async function checkJournal(id: number) {
    const journal = journals.find((item) => item.id === id) ?? null;
    setSelectedJournal(journal);
    setRefreshingJournal(id);
    setMessage(`正在刷新“${journal?.title ?? "期刊"}”的最新文献…`);
    try {
      const result = await runJournal(id);
      const papers = await fetchJournalPapers(id);
      setLatestPapers(papers);
      setMessage(`刷新完成：发现 ${result.new_count} 篇此前未见的文献，共显示 ${papers.length} 篇。`);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "期刊刷新失败");
    } finally {
      setRefreshingJournal(null);
    }
  }

  async function checkSearch(id: number) {
    const result = await runSavedSearch(id);
    setMessage(`检索完成：发现 ${result.new_count} 篇此前未见的文献。`);
    await reload();
  }

  return <div className="page updates-page">
    <header className="page-header"><div><p className="eyebrow">打开 App 时更新</p><h1>关注与保存检索</h1></div></header>
    <section className="updates-card">
      <div className="section-heading"><div><h2>喜欢的期刊</h2><p>添加期刊卡片；点击卡片会从免费来源刷新最新文献，并严格核对期刊字段。</p></div></div>
      <form className="inline-create" onSubmit={(event) => void submit(event)}><label className="sr-only" htmlFor="journal-title">期刊名称</label><input id="journal-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如 Catalysis Today" /><button className="primary-button" type="submit">添加期刊</button></form>
      {journals.length === 0
        ? <div className="empty-inline">还没有添加喜欢的期刊。</div>
        : <div className="journal-card-grid">{journals.map((journal) => <article key={journal.id} className={selectedJournal?.id === journal.id ? "journal-card selected" : "journal-card"}>
          <button className="journal-card-main" type="button" onClick={() => void checkJournal(journal.id)} disabled={refreshingJournal === journal.id}>
            <span className="journal-monogram">{journal.title.slice(0, 1).toUpperCase()}</span>
            <span><h3>{journal.title}</h3><p>上次检查：{timeLabel(journal.last_success_at)}</p><strong>{journal.last_match_count} 篇最新匹配</strong>{journal.last_error && <small className="error-text">{journal.last_error}</small>}</span>
            <em>{refreshingJournal === journal.id ? "刷新中…" : "打开并刷新 →"}</em>
          </button>
          <label><input type="checkbox" checked={journal.enabled} onChange={(event) => void setJournalEnabled(journal.id, event.target.checked).then(reload)} /> 自动检查</label>
        </article>)}</div>}
      {selectedJournal && <section className="journal-latest" aria-label={`${selectedJournal.title} 最新文献`}>
        <div className="section-heading"><div><h2>{selectedJournal.title}</h2><p>每次打开卡片都会联网刷新，并按年份展示最新文献。</p></div><button type="button" onClick={() => void checkJournal(selectedJournal.id)} disabled={refreshingJournal === selectedJournal.id}>刷新</button></div>
        {latestPapers.length === 0
          ? <div className="empty-inline">刷新后暂未找到严格匹配该期刊的文献。</div>
          : <div className="journal-paper-list">{latestPapers.map((paper) => <article key={paper.id}><div><h3>{paper.title}</h3><p>{paper.year ?? "年份暂缺"}{paper.doi ? ` · DOI ${paper.doi}` : ""}</p><p>{paper.abstract || "暂无摘要"}</p></div>{paper.url && <a href={paper.url} target="_blank" rel="noreferrer">查看来源</a>}</article>)}</div>}
      </section>}
    </section>
    <section className="updates-card">
      <div className="section-heading"><div><h2>保存的检索</h2><p>与上次结果逐条比较，同一文献不会重复提醒。</p></div><a href="#search">创建保存检索</a></div>
      {searches.length === 0 ? <div className="empty-inline">还没有保存检索。</div> : <div className="subscription-list">{searches.map((item) => <article key={item.id}><div><h3>{item.name}</h3><p>{item.query.text} · 上次新增 {item.last_new_count} 篇 · {timeLabel(item.last_success_at)}</p>{item.last_error && <small className="error-text">{item.last_error}</small>}</div><label><input type="checkbox" checked={item.enabled} onChange={(event) => void setSavedSearchEnabled(item.id, event.target.checked).then(reload)} /> 自动检查</label><button type="button" onClick={() => void checkSearch(item.id)}>立即运行</button><button className="danger-link" type="button" onClick={() => void deleteSavedSearch(item.id).then(reload)}>删除</button></article>)}</div>}
    </section>
    <p className="action-message" role="status">{message}</p>
  </div>;
}
