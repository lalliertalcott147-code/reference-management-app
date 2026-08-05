import { useEffect, useRef, useState } from "react";
import {
  addWorkspaceCard,
  addWorkspaceElement,
  deleteWorkspaceCard,
  deleteWorkspaceElement,
  fetchJob,
  fetchLibraryWorkspace,
  saveLibraryWorkspace,
  submitTranslation,
  type LibraryPaper,
  type LibraryWorkspace as Workspace,
  type WorkspaceCard,
  type WorkspaceElement,
  updateWorkspaceCard,
  updateWorkspaceElement,
} from "../api";

interface DragState {
  kind: "note" | "card" | "element";
  id: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
}

async function waitForTranslation(jobId: number): Promise<void> {
  for (;;) {
    const job = await fetchJob(jobId);
    if (job.status === "completed") return;
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(job.error_message ?? "翻译未完成");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 300));
  }
}

export function LibraryWorkspace({
  libraryId,
  papers,
}: {
  libraryId?: number;
  papers: LibraryPaper[];
}) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [paperId, setPaperId] = useState("");
  const [status, setStatus] = useState("正在读取总笔记…");
  const [dirty, setDirty] = useState(false);
  const [tool, setTool] = useState<"select" | "text" | "line">("select");
  const [selectedElement, setSelectedElement] = useState<number | null>(null);
  const drag = useRef<DragState | null>(null);

  async function reload() {
    const value = await fetchLibraryWorkspace(libraryId);
    setWorkspace(value);
    setStatus("");
  }

  useEffect(() => {
    let active = true;
    void fetchLibraryWorkspace(libraryId).then((value) => {
      if (active) {
        setWorkspace(value);
        setStatus("");
      }
    }).catch((error: unknown) => {
      if (active) setStatus(error instanceof Error ? error.message : "总笔记读取失败");
    });
    return () => { active = false; };
  }, [libraryId]);

  useEffect(() => {
    if (!workspace || !dirty) return;
    const timer = window.setTimeout(() => {
      void saveLibraryWorkspace(libraryId, workspace).then((result) => {
        setWorkspace((current) => current ? { ...current, version: result.version } : current);
        setDirty(false);
        setStatus(`总笔记已保存 · v${result.version}`);
      }).catch((error: unknown) => {
        setStatus(error instanceof Error ? error.message : "总笔记保存失败");
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [dirty, libraryId, workspace]);

  function beginDrag(
    event: React.PointerEvent,
    kind: DragState["kind"],
    id: number,
    originX: number,
    originY: number,
  ) {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = {
      kind, id, startX: event.clientX, startY: event.clientY, originX, originY,
    };
  }

  function moveDrag(event: React.PointerEvent) {
    const active = drag.current;
    if (!active || !workspace) return;
    const x = Math.max(0, active.originX + event.clientX - active.startX);
    const y = Math.max(0, active.originY + event.clientY - active.startY);
    if (active.kind === "note") {
      setWorkspace({ ...workspace, note_x: x, note_y: y });
    } else if (active.kind === "card") {
      setWorkspace({
        ...workspace,
        cards: workspace.cards.map((card) => card.id === active.id ? { ...card, x, y } : card),
      });
    } else {
      setWorkspace({
        ...workspace,
        elements: workspace.elements.map((element) => (
          element.id === active.id ? { ...element, x, y } : element
        )),
      });
    }
  }

  function finishDrag() {
    const active = drag.current;
    drag.current = null;
    if (!active || !workspace) return;
    if (active.kind === "note") {
      void saveLibraryWorkspace(libraryId, workspace).then((result) => {
        setWorkspace((current) => current ? { ...current, version: result.version } : current);
        setStatus("总笔记位置已保存");
      });
    } else if (active.kind === "card") {
      const card = workspace.cards.find((item) => item.id === active.id);
      if (card) void updateWorkspaceCard(card.id, card).then(() => setStatus("文章卡片位置已保存"));
    } else {
      const element = workspace.elements.find((item) => item.id === active.id);
      if (element) void updateWorkspaceElement(element).then(() => setStatus("画布元素位置已保存"));
    }
  }

  async function addElement(event: React.MouseEvent<HTMLDivElement>) {
    if (tool === "select" || event.target !== event.currentTarget || !workspace) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const element: Omit<WorkspaceElement, "id"> = {
      element_type: tool,
      x: Math.max(0, event.clientX - bounds.left + event.currentTarget.scrollLeft),
      y: Math.max(0, event.clientY - bounds.top + event.currentTarget.scrollTop),
      width: tool === "text" ? 260 : 220,
      height: tool === "text" ? 140 : 20,
      content: "",
      color: "#315f59",
    };
    try {
      const result = await addWorkspaceElement(libraryId, element);
      setWorkspace((current) => current ? {
        ...current,
        elements: [...current.elements, { ...element, id: result.id }],
      } : current);
      setSelectedElement(result.id);
      setTool("select");
      setStatus(tool === "text" ? "文字块已添加，可拖动和编辑" : "直线已添加，可拖动");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "画布元素添加失败");
    }
  }

  function changeElement(elementId: number, patch: Partial<WorkspaceElement>) {
    setWorkspace((current) => current ? {
      ...current,
      elements: current.elements.map((element) => (
        element.id === elementId ? { ...element, ...patch } : element
      )),
    } : current);
  }

  async function saveElement(elementId: number) {
    const element = workspace?.elements.find((item) => item.id === elementId);
    if (!element) return;
    await updateWorkspaceElement(element);
    setStatus("画布元素已保存");
  }

  async function removeElement(elementId: number) {
    await deleteWorkspaceElement(elementId);
    setWorkspace((current) => current ? {
      ...current,
      elements: current.elements.filter((element) => element.id !== elementId),
    } : current);
    setSelectedElement((current) => current === elementId ? null : current);
    setStatus("画布元素已删除");
  }

  async function addCard() {
    const selected = Number(paperId);
    if (!selected) return;
    await addWorkspaceCard(libraryId, selected);
    setPaperId("");
    await reload();
    setStatus("文章卡片已加入总笔记");
  }

  async function translate(card: WorkspaceCard, field: "title" | "abstract") {
    setStatus(`正在翻译${field === "title" ? "题目" : "摘要"}…`);
    try {
      const { job_id: jobId } = await submitTranslation(card.paper_id, field);
      await waitForTranslation(jobId);
      await reload();
      setStatus("翻译已保存到文章卡片");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "翻译失败");
    }
  }

  if (!workspace) return <div className="workspace-loading" role="status">{status}</div>;
  const available = papers.filter((paper) => !workspace.cards.some((card) => card.paper_id === paper.id));
  const extent = Math.max(
    760,
    workspace.note_y + workspace.note_height + 60,
    ...workspace.cards.map((card) => card.y + card.height + 60),
    ...workspace.elements.map((element) => element.y + element.height + 60),
  );
  return <section className="knowledge-workspace">
    <div className="workspace-actions">
      <select aria-label="选择要加入总笔记的文章" value={paperId} onChange={(event) => setPaperId(event.target.value)}>
        <option value="">选择文章卡片…</option>
        {available.map((paper) => <option key={paper.id} value={paper.id}>{paper.title}</option>)}
      </select>
      <button className="primary-button" type="button" disabled={!paperId} onClick={() => void addCard()}>加入文章卡片</button>
      <span role="status">{status}</span>
    </div>
    <div className="workspace-board">
      <aside className="workspace-toolbox" aria-label="总笔记工具栏">
        <strong>工具</strong>
        <button type="button" aria-label="选择或移动" className={tool === "select" ? "active" : ""} aria-pressed={tool === "select"} onClick={() => setTool("select")}><span>↖</span>选择/移动</button>
        <button type="button" aria-label="添加文字" className={tool === "text" ? "active" : ""} aria-pressed={tool === "text"} onClick={() => setTool("text")}><span>T</span>添加文字</button>
        <button type="button" aria-label="添加直线" className={tool === "line" ? "active" : ""} aria-pressed={tool === "line"} onClick={() => setTool("line")}><span>／</span>添加直线</button>
        <button type="button" aria-label="删除选中" disabled={selectedElement === null} onClick={() => { if (selectedElement !== null) void removeElement(selectedElement); }}><span>×</span>删除选中</button>
        {tool !== "select" && <small>在画布空白处单击放置</small>}
      </aside>
      <div className={`workspace-canvas tool-${tool}`} style={{ minHeight: extent }} onClick={(event) => void addElement(event)} onPointerMove={moveDrag} onPointerUp={finishDrag} onPointerCancel={finishDrag}>
        <article className="workspace-note" style={{ left: workspace.note_x, top: workspace.note_y, width: workspace.note_width, height: workspace.note_height }}>
          <header onPointerDown={(event) => beginDrag(event, "note", 0, workspace.note_x, workspace.note_y)}>总笔记 <span>拖动排布</span></header>
          <textarea aria-label="总笔记" value={workspace.body} onChange={(event) => { setWorkspace({ ...workspace, body: event.target.value }); setDirty(true); setStatus("等待保存…"); }} placeholder="在这里汇总思路、结论和研究脉络…" />
        </article>
        {workspace.elements.map((element) => element.element_type === "text"
          ? <article className={`workspace-text-element ${selectedElement === element.id ? "selected" : ""}`} key={element.id} style={{ left: element.x, top: element.y, width: element.width, height: element.height, borderColor: element.color }} onClick={(event) => { event.stopPropagation(); setSelectedElement(element.id); }}>
            <header onPointerDown={(event) => { setSelectedElement(element.id); beginDrag(event, "element", element.id, element.x, element.y); }}><span>文字 · 拖动</span><button type="button" aria-label={`删除文字 ${element.id}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => void removeElement(element.id)}>×</button></header>
            <textarea aria-label={`文字元素 ${element.id}`} value={element.content} placeholder="输入文字…" onPointerDown={(event) => event.stopPropagation()} onChange={(event) => changeElement(element.id, { content: event.target.value })} onBlur={() => void saveElement(element.id)} />
            <label>颜色 <input aria-label={`文字 ${element.id} 颜色`} type="color" value={element.color} onChange={(event) => changeElement(element.id, { color: event.target.value })} onBlur={() => void saveElement(element.id)} /></label>
          </article>
          : <button type="button" className={`workspace-line-element ${selectedElement === element.id ? "selected" : ""}`} aria-label={`直线元素 ${element.id}`} key={element.id} style={{ left: element.x, top: element.y, width: element.width, height: element.height, color: element.color }} onPointerDown={(event) => { event.stopPropagation(); setSelectedElement(element.id); beginDrag(event, "element", element.id, element.x, element.y); }} onClick={(event) => { event.stopPropagation(); setSelectedElement(element.id); }}><svg viewBox={`0 0 ${element.width} ${element.height}`} preserveAspectRatio="none"><line x1="2" y1={element.height - 2} x2={element.width - 2} y2="2" stroke="currentColor" strokeWidth="3" /></svg></button>)}
        {workspace.cards.map((card) => <article className="workspace-paper-card" key={card.id} style={{ left: card.x, top: card.y, width: card.width, height: card.height }}>
        <header onPointerDown={(event) => beginDrag(event, "card", card.id, card.x, card.y)}><span>文章卡片 · 拖动排布</span><button type="button" aria-label={`移除 ${card.title}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => void deleteWorkspaceCard(card.id).then(reload)}>×</button></header>
        <div className="workspace-card-scroll">
          <h2>{card.title}</h2>
          {card.title_translation && <p className="card-translation">{card.title_translation}</p>}
          <button type="button" onClick={() => void translate(card, "title")}>翻译题目</button>
          <h3>摘要</h3><p>{card.abstract || "暂无摘要"}</p>
          {card.abstract_translation && <p className="card-translation">{card.abstract_translation}</p>}
          <button type="button" disabled={!card.abstract} onClick={() => void translate(card, "abstract")}>翻译摘要</button>
          <h3>文章笔记汇总</h3>
          {card.notes.length ? card.notes.map((note) => <blockquote key={note.id}>{note.body}</blockquote>) : <p>暂无文章笔记</p>}
          {card.file_id && <a className="reader-link" href={`#reader?paper=${card.paper_id}&file=${card.file_id}`}>阅读并翻译 PDF</a>}
        </div>
        </article>)}
      </div>
    </div>
  </section>;
}
