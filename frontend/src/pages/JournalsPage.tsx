import { type FormEvent, useEffect, useState } from "react";
import {
  type JournalSubscription,
  type SavedSearch,
  deleteSavedSearch,
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

  async function reload() {
    const [nextJournals, nextSearches] = await Promise.all([
      fetchJournalSubscriptions(), fetchSavedSearches(),
    ]);
    setJournals(nextJournals);
    setSearches(nextSearches);
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
    const result = await runJournal(id);
    setMessage(`检查完成：发现 ${result.new_count} 篇此前未见的文献。`);
    await reload();
  }

  async function checkSearch(id: number) {
    const result = await runSavedSearch(id);
    setMessage(`检索完成：发现 ${result.new_count} 篇此前未见的文献。`);
    await reload();
  }

  return <div className="page updates-page">
    <header className="page-header"><div><p className="eyebrow">打开 App 时更新</p><h1>关注与保存检索</h1></div></header>
    <section className="updates-card">
      <div className="section-heading"><div><h2>关注期刊</h2><p>按期刊名检查开放来源，结果会严格核对期刊字段。</p></div></div>
      <form className="inline-create" onSubmit={(event) => void submit(event)}><label className="sr-only" htmlFor="journal-title">期刊名称</label><input id="journal-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如 Catalysis Today" /><button className="primary-button" type="submit">关注</button></form>
      {journals.length === 0 ? <div className="empty-inline">还没有关注期刊。</div> : <div className="subscription-list">{journals.map((journal) => <article key={journal.id}><div><h3>{journal.title}</h3><p>上次检查：{timeLabel(journal.last_success_at)} · 匹配 {journal.last_match_count} 篇</p>{journal.last_error && <small className="error-text">{journal.last_error}</small>}</div><label><input type="checkbox" checked={journal.enabled} onChange={(event) => void setJournalEnabled(journal.id, event.target.checked).then(reload)} /> 自动检查</label><button type="button" onClick={() => void checkJournal(journal.id)}>立即检查</button></article>)}</div>}
    </section>
    <section className="updates-card">
      <div className="section-heading"><div><h2>保存的检索</h2><p>与上次结果逐条比较，同一文献不会重复提醒。</p></div><a href="#search">创建保存检索</a></div>
      {searches.length === 0 ? <div className="empty-inline">还没有保存检索。</div> : <div className="subscription-list">{searches.map((item) => <article key={item.id}><div><h3>{item.name}</h3><p>{item.query.text} · 上次新增 {item.last_new_count} 篇 · {timeLabel(item.last_success_at)}</p>{item.last_error && <small className="error-text">{item.last_error}</small>}</div><label><input type="checkbox" checked={item.enabled} onChange={(event) => void setSavedSearchEnabled(item.id, event.target.checked).then(reload)} /> 自动检查</label><button type="button" onClick={() => void checkSearch(item.id)}>立即运行</button><button className="danger-link" type="button" onClick={() => void deleteSavedSearch(item.id).then(reload)}>删除</button></article>)}</div>}
    </section>
    <p className="action-message" role="status">{message}</p>
  </div>;
}
