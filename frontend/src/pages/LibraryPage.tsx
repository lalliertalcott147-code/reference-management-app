import { type FormEvent, useEffect, useState } from "react";
import {
  assignTag,
  createLibrary,
  deleteLibrary,
  exportPapers,
  fetchLibraries,
  fetchLibraryPapers,
  type LibraryPaper,
  type LibraryRecord,
  restoreLibrary,
  saveNote,
  updatePaperState,
} from "../api";
import { LibraryWorkspace } from "../components/LibraryWorkspace";
import { PdfUpload } from "../components/PdfUpload";

function NoteEditor({ paper, libraryId }: { paper: LibraryPaper; libraryId?: number }) {
  const [body, setBody] = useState(paper.note);
  const [noteId, setNoteId] = useState(paper.note_id);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState("");
  useEffect(() => {
    if (!dirty) return;
    const timer = window.setTimeout(() => {
      void saveNote(paper.id, body, noteId, libraryId).then((result) => {
        setNoteId(result.note_id);
        setDirty(false);
        setStatus(`已保存 · v${result.version}`);
      }).catch(() => setStatus("保存失败，请重试"));
    }, 700);
    return () => window.clearTimeout(timer);
  }, [body, dirty, libraryId, noteId, paper.id]);
  const pdfLocation = /\[PDF 第 (\d+) 页 .* 文件 (\d+)\]/.exec(body);
  return <div className="note-editor">
    <textarea aria-label={`${paper.title}笔记`} value={body} onChange={(event) => {
      setBody(event.target.value); setDirty(true); setStatus("等待保存…");
    }} placeholder="添加本地笔记…" />
    {pdfLocation && <a className="reader-link" href={`#reader?paper=${paper.id}&file=${pdfLocation[2]}&page=${pdfLocation[1]}`}>跳回 PDF 第 {pdfLocation[1]} 页</a>}
    <small role="status">{status}</small>
  </div>;
}

export function LibraryPage() {
  const [libraries, setLibraries] = useState<LibraryRecord[]>([]);
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [selectedLibrary, setSelectedLibrary] = useState<number | undefined>();
  const [view, setView] = useState<"list" | "workspace">("list");
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [newLibrary, setNewLibrary] = useState("");
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [trashVisible, setTrashVisible] = useState(false);
  const [message, setMessage] = useState("");

  async function loadLibraries(includeDeleted = trashVisible) {
    const result = await fetchLibraries(includeDeleted);
    setLibraries(result);
    if (selectedLibrary === undefined) {
      setSelectedLibrary(result.find((item) => !item.deleted_at)?.id);
    }
  }
  async function loadPapers(search = query) {
    setPapers(await fetchLibraryPapers(selectedLibrary, search));
  }
  useEffect(() => {
    let active = true;
    void fetchLibraries(false).then((result) => {
      if (!active) return;
      setLibraries(result);
      setSelectedLibrary(result.find((item) => !item.deleted_at)?.id);
    });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    void fetchLibraryPapers(selectedLibrary).then((result) => {
      if (active) setPapers(result);
    });
    return () => { active = false; };
  }, [selectedLibrary]);

  async function addLibrary(event: FormEvent) {
    event.preventDefault();
    if (!newLibrary.trim()) return;
    const created = await createLibrary(newLibrary);
    setNewLibrary("");
    await loadLibraries();
    setSelectedLibrary(created.id);
  }

  async function setState(paper: LibraryPaper, patch: Partial<LibraryPaper>) {
    const updated = { ...paper, ...patch };
    await updatePaperState(updated);
    setPapers((current) => current.map((item) => item.id === paper.id ? updated : item));
  }

  async function applyTag() {
    if (!tag.trim() || checked.size === 0) return;
    await assignTag(tag, [...checked], selectedLibrary);
    setMessage(`已给 ${checked.size} 篇文献添加标签“${tag}”`);
    setTag("");
  }

  const activeLibraries = libraries.filter((item) => !item.deleted_at);
  const deletedLibraries = libraries.filter((item) => item.deleted_at);
  return <div className="page library-page">
    <header className="page-header">
      <div><p className="eyebrow">永久本地收藏</p><h1>知识库</h1></div>
      <div className="page-actions"><PdfUpload onComplete={() => void loadPapers()} /><button className="secondary-button" type="button" onClick={() => { setTrashVisible((value) => !value); void loadLibraries(!trashVisible); }}>回收站</button></div>
    </header>
    <div className="library-layout">
      <aside className="library-sidebar">
        <form onSubmit={(event) => void addLibrary(event)}><input aria-label="新知识库名称" value={newLibrary} onChange={(event) => setNewLibrary(event.target.value)} placeholder="新建知识库" /><button type="submit" aria-label="创建知识库">＋</button></form>
        <button type="button" className={selectedLibrary === undefined ? "active" : ""} onClick={() => { setSelectedLibrary(undefined); setView("list"); }}>全部文献</button>
        {activeLibraries.map((library) => <div className="library-link" key={library.id}><button type="button" className={selectedLibrary === library.id ? "active" : ""} onClick={() => setSelectedLibrary(library.id)}><span>{library.name}</span><small>{library.paper_count}</small></button><button type="button" aria-label={`删除 ${library.name}`} onClick={() => void deleteLibrary(library.id).then(() => loadLibraries())}>×</button></div>)}
      </aside>
      <section className="library-main">
        {selectedLibrary !== undefined && <nav className="library-view-tabs" aria-label="知识库视图"><button type="button" className={view === "list" ? "active" : ""} onClick={() => setView("list")}>文献列表</button><button type="button" className={view === "workspace" ? "active" : ""} onClick={() => setView("workspace")}>总笔记</button></nav>}
        {view === "workspace" && selectedLibrary !== undefined
          ? <LibraryWorkspace key={selectedLibrary} libraryId={selectedLibrary} papers={papers} />
          : <>
            <form className="library-search" onSubmit={(event) => { event.preventDefault(); void loadPapers(query); }}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题名、作者、摘要、译文、标签和笔记" /><button className="primary-button" type="submit">本地搜索</button></form>
            {checked.size > 0 && <div className="batch-bar"><strong>已选 {checked.size} 篇</strong><input value={tag} onChange={(event) => setTag(event.target.value)} placeholder="标签名称" /><button type="button" onClick={() => void applyTag()}>添加标签</button>{(["bibtex", "ris", "csv"] as const).map((format) => <button key={format} type="button" onClick={() => void exportPapers([...checked], format)}>导出 {format.toUpperCase()}</button>)}</div>}
            <span className="action-message" role="status">{message}</span>
            {papers.length === 0 && <div className="empty-state"><span className="empty-icon">□</span><h2>这里还没有文献</h2><p>从检索页加入，或调整本地搜索条件。</p><a className="primary-button" href="#search">去检索</a></div>}
            <div className="library-paper-list">{papers.map((paper) => <article key={paper.id} className="library-paper"><label><input type="checkbox" aria-label={`选择 ${paper.title}`} checked={checked.has(paper.id)} onChange={(event) => setChecked((current) => { const next = new Set(current); if (event.target.checked) next.add(paper.id); else next.delete(paper.id); return next; })} /></label><div><h2>{paper.title}</h2><p>{paper.journal ?? "期刊暂缺"} · {paper.year ?? "年份暂缺"} {paper.has_pdf ? "· 已有 PDF" : "· 无 PDF"}</p><div className="state-row"><button className={paper.liked ? "on" : ""} type="button" onClick={() => void setState(paper, { liked: !paper.liked })}>♡ 喜欢</button><select aria-label={`${paper.title}阅读状态`} value={paper.reading_status} onChange={(event) => void setState(paper, { reading_status: event.target.value as LibraryPaper["reading_status"] })}><option value="unread">未读</option><option value="reading">在读</option><option value="read">已读</option></select>{paper.file_id && <a className="reader-link" href={`#reader?paper=${paper.id}&file=${paper.file_id}`}>阅读 PDF</a>}<PdfUpload paperId={paper.id} compact onComplete={(_paperId, fileId) => setPapers((current) => current.map((item) => item.id === paper.id ? { ...item, has_pdf: true, file_id: fileId } : item))} /></div><NoteEditor paper={paper} libraryId={selectedLibrary} /></div></article>)}</div>
          </>}
      </section>
    </div>
    {trashVisible && <section className="trash-panel"><h2>30 天回收站</h2>{deletedLibraries.length === 0 ? <p>回收站为空</p> : deletedLibraries.map((library) => <div key={library.id}><span>{library.name}</span><button type="button" onClick={() => void restoreLibrary(library.id).then(() => loadLibraries(true))}>恢复</button></div>)}</section>}
  </div>;
}
