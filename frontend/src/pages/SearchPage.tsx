import { type FormEvent, useMemo, useRef, useState } from "react";
import {
  type MergedPaper,
  type SearchResponse,
  createSavedSearch,
  savePaper,
  searchPapers,
} from "../api";
import { PaperDetail } from "../components/PaperDetail";
import { PdfUpload } from "../components/PdfUpload";

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; result: SearchResponse }
  | { kind: "error"; message: string };

const sourceLabels = { wos: "WoS", openalex: "OpenAlex", crossref: "Crossref", wos_export: "WoS 导入", pdf: "PDF" };

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [field, setField] = useState("topic");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  const [selected, setSelected] = useState<MergedPaper | null>(null);
  const [abstractOnly, setAbstractOnly] = useState(false);
  const [sort, setSort] = useState("relevance");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [readingStatus, setReadingStatus] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [savedSearchName, setSavedSearchName] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const controller = useRef<AbortController | null>(null);

  const visiblePapers = useMemo(() => {
    if (state.kind !== "ready") return [];
    const filtered = state.result.papers.filter((paper) => {
      if (abstractOnly && !paper.abstract) return false;
      return sourceFilter === "all" || paper.sources.some((source) => source.source === sourceFilter);
    });
    return [...filtered].sort((left, right) => {
      if (sort === "year") return (right.year ?? 0) - (left.year ?? 0);
      if (sort === "citations") return (right.citations ?? 0) - (left.citations ?? 0);
      return 0;
    });
  }, [abstractOnly, sort, sourceFilter, state]);

  async function runSearch(refresh = false) {
    if (!query.trim()) return;
    controller.current?.abort();
    controller.current = new AbortController();
    setState({ kind: "loading" });
    try {
      const result = await searchPapers({
        text: query,
        field,
        year_from: yearFrom ? Number(yearFrom) : null,
        year_to: yearTo ? Number(yearTo) : null,
        sort: sort === "year" ? "year_desc" : sort,
        refresh,
      }, controller.current.signal);
      setState({ kind: "ready", result });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState({ kind: "error", message: error instanceof Error ? error.message : "检索失败" });
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void runSearch();
  }

  async function persist(
    paper: MergedPaper,
    options: { liked?: boolean; readingStatus?: string } = {},
  ): Promise<number | null> {
    try {
      const result = await savePaper(paper, {
        liked: options.liked,
        saved: true,
        reading_status: options.readingStatus ?? readingStatus[paper.identity] ?? "unread",
      });
      setSaved((current) => ({ ...current, [paper.identity]: true }));
      if (options.readingStatus) {
        setReadingStatus((current) => ({ ...current, [paper.identity]: options.readingStatus ?? "unread" }));
      }
      return result.paper_id;
    } catch (error) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "保存失败" });
      return null;
    }
  }

  async function saveSelected() {
    await Promise.all(
      visiblePapers.filter((paper) => checked.has(paper.identity)).map((paper) => persist(paper)),
    );
    setChecked(new Set());
  }

  async function saveCurrentSearch() {
    if (!query.trim() || !savedSearchName.trim()) return;
    try {
      await createSavedSearch({
        name: savedSearchName,
        text: query,
        field,
        year_from: yearFrom ? Number(yearFrom) : null,
        year_to: yearTo ? Number(yearTo) : null,
        sort: sort === "year" ? "year_desc" : sort,
      });
      setSavedSearchName("");
      setSaveMessage("检索已保存；可在“期刊”页手动运行或管理自动检查。");
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : "保存检索失败");
    }
  }

  return <div className="page search-page">
    <header className="page-header">
      <div><p className="eyebrow">多来源检索</p><h1>检索催化文献</h1></div>
      <a className="secondary-button" href="#import">导入 WoS 记录</a>
    </header>
    <form className="search-form" onSubmit={submit}>
      <label className="search-box">
        <span className="sr-only">检索词</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入关键词、题名、作者或 DOI" />
      </label>
      <select value={field} onChange={(event) => setField(event.target.value)} aria-label="检索字段">
        <option value="topic">主题</option><option value="title">题名</option>
        <option value="author">作者</option><option value="doi">DOI</option>
      </select>
      <button className="primary-button" type="submit" disabled={state.kind === "loading"}>{state.kind === "loading" ? "检索中…" : "检索"}</button>
      {state.kind === "loading" && <button className="text-button" type="button" onClick={() => controller.current?.abort()}>取消</button>}
      <details className="advanced-search">
        <summary>高级条件</summary>
        <div><label>起始年份<input type="number" min="1600" max="2200" value={yearFrom} onChange={(event) => setYearFrom(event.target.value)} /></label>
          <label>结束年份<input type="number" min="1600" max="2200" value={yearTo} onChange={(event) => setYearTo(event.target.value)} /></label></div>
      </details>
    </form>
    {state.kind === "ready" && <div className="source-statuses" aria-label="来源状态">
      {state.result.statuses.map((status) => <span key={status.source} className={`source-state ${status.state}`} title={status.message}>{sourceLabels[status.source]} · {status.state}</span>)}
    </div>}
    {state.kind === "error" && <div className="notice error" role="alert"><strong>检索没有完成</strong><span>{state.message}</span><button type="button" onClick={() => void runSearch(true)}>重新获取</button></div>}
    {state.kind === "ready" && <div className="result-toolbar">
      <strong>{visiblePapers.length} 条合并结果</strong>
      <label><input type="checkbox" checked={abstractOnly} onChange={(event) => setAbstractOnly(event.target.checked)} /> 仅看有摘要</label>
      <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} aria-label="来源筛选"><option value="all">全部来源</option><option value="wos">WoS</option><option value="openalex">OpenAlex</option><option value="crossref">Crossref</option></select>
      <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="结果排序"><option value="relevance">相关性</option><option value="year">年份</option><option value="citations">被引次数</option></select>
      {checked.size > 0 && <button type="button" className="secondary-button compact" onClick={() => void saveSelected()}>批量加入（{checked.size}）</button>}
    </div>}
    {state.kind === "ready" && <div className="saved-search-bar"><label>保存本次检索<input aria-label="保存检索名称" value={savedSearchName} onChange={(event) => setSavedSearchName(event.target.value)} placeholder="给它起个名字" /></label><button className="secondary-button compact" type="button" disabled={!savedSearchName.trim()} onClick={() => void saveCurrentSearch()}>保存检索</button><span role="status">{saveMessage}</span></div>}
    {state.kind === "idle" && <div className="empty-state"><span className="empty-icon">⌕</span><h2>从一个明确的问题开始</h2><p>WoS 负责主检索，开放来源补全摘要；每个字段都保留来源。</p></div>}
    {state.kind === "ready" && visiblePapers.length === 0 && <div className="empty-state"><h2>没有符合当前筛选的结果</h2><p>可取消“仅看有摘要”，或调整关键词和年份。</p></div>}
    <div className="paper-list">
      {visiblePapers.map((paper) => <article className="paper-card" key={paper.identity}>
        <div className="paper-card-main"><label className="select-paper"><input type="checkbox" aria-label={`选择 ${paper.title}`} checked={checked.has(paper.identity)} onChange={(event) => setChecked((current) => { const next = new Set(current); if (event.target.checked) next.add(paper.identity); else next.delete(paper.identity); return next; })} /> 批量选择</label><div className="source-badges">{paper.sources.map((source) => <span key={`${source.source}-${source.source_id}`}>{sourceLabels[source.source]}</span>)}</div>
          <button className="title-button" type="button" onClick={() => setSelected(paper)}>{paper.title}</button>
          <p className="paper-authors">{paper.authors.join("；") || "作者暂缺"}</p>
          <p className="paper-meta">{paper.journal ?? "来源期刊暂缺"} · {paper.year ?? "年份暂缺"} {paper.doi ? `· ${paper.doi}` : ""}</p>
          <p className="abstract-preview">{paper.abstract ?? "当前开放来源未提供摘要。"}</p></div>
        <div className="paper-actions"><button type="button" onClick={() => void persist(paper)}>{saved[paper.identity] ? "已加入知识库" : "加入知识库"}</button>
          <button type="button" onClick={() => void persist(paper, { liked: true })}>喜欢</button><select aria-label={`${paper.title}阅读状态`} value={readingStatus[paper.identity] ?? "unread"} onChange={(event) => void persist(paper, { readingStatus: event.target.value })}><option value="unread">未读</option><option value="reading">在读</option><option value="read">已读</option></select><button type="button" onClick={() => setSelected(paper)}>查看详情</button><PdfUpload compact ensurePaperId={() => persist(paper)} /></div>
      </article>)}
    </div>
    {selected && <PaperDetail paper={selected} onClose={() => setSelected(null)} ensureSaved={() => persist(selected)} />}
  </div>;
}
