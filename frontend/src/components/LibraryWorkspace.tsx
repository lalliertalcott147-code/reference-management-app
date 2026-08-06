import { type CSSProperties, useEffect, useRef, useState } from "react";
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

type CanvasTool = "select" | WorkspaceElement["element_type"];

interface LegacyDrag {
  kind: "note" | "card";
  mode: "move" | "resize";
  id: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  originWidth: number;
  originHeight: number;
}

interface ElementTransform {
  mode: "move" | "resize" | "rotate";
  startX: number;
  startY: number;
  originals: WorkspaceElement[];
  targetId: number;
  centerX: number;
  centerY: number;
  startAngle: number;
}

interface HistoryEntry {
  kind: "add" | "delete" | "update";
  before: WorkspaceElement[];
  after: WorkspaceElement[];
}

const FONT_FAMILIES = ["Microsoft YaHei", "SimSun", "Arial", "Georgia"];
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

function cloneElements(elements: WorkspaceElement[]): WorkspaceElement[] {
  return elements.map((element) => ({ ...element }));
}

function elementWithoutId(element: WorkspaceElement): Omit<WorkspaceElement, "id"> {
  return {
    element_type: element.element_type,
    x: element.x,
    y: element.y,
    width: element.width,
    height: element.height,
    rotation: element.rotation,
    content: element.content,
    text_color: element.text_color,
    fill_color: element.fill_color,
    border_color: element.border_color,
    border_width: element.border_width,
    font_size: element.font_size,
    font_family: element.font_family,
    text_align: element.text_align,
    z_index: element.z_index,
    group_id: element.group_id,
  };
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
  const [tool, setTool] = useState<CanvasTool>("select");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [clipboard, setClipboard] = useState<WorkspaceElement[]>([]);
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([]);
  const [zoom, setZoom] = useState(1);
  const [canvasHeight, setCanvasHeight] = useState(1400);
  const legacyDrag = useRef<LegacyDrag | null>(null);
  const transform = useRef<ElementTransform | null>(null);
  const imageInput = useRef<HTMLInputElement | null>(null);
  const paperSelect = useRef<HTMLSelectElement | null>(null);
  const editStart = useRef<Map<number, WorkspaceElement>>(new Map());

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
        setSelectedIds([]);
        setUndoStack([]);
        setRedoStack([]);
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

  function mergeElements(changed: WorkspaceElement[]) {
    const byId = new Map(changed.map((element) => [element.id, element]));
    setWorkspace((current) => current ? {
      ...current,
      elements: current.elements.map((element) => byId.get(element.id) ?? element),
    } : current);
  }

  function record(entry: HistoryEntry) {
    setUndoStack((current) => [...current.slice(-79), entry]);
    setRedoStack([]);
  }

  async function persistUpdate(before: WorkspaceElement[], after: WorkspaceElement[], message: string) {
    if (JSON.stringify(before) === JSON.stringify(after)) return;
    await Promise.all(after.map(updateWorkspaceElement));
    record({ kind: "update", before: cloneElements(before), after: cloneElements(after) });
    setStatus(message);
  }

  async function applyHistory(entry: HistoryEntry, undo: boolean) {
    if (entry.kind === "update") {
      const target = undo ? entry.before : entry.after;
      await Promise.all(target.map(updateWorkspaceElement));
      mergeElements(cloneElements(target));
      return;
    }
    const elements = entry.kind === "add" ? entry.after : entry.before;
    const shouldDelete = entry.kind === "add" ? undo : !undo;
    if (shouldDelete) {
      await Promise.all(elements.map((element) => deleteWorkspaceElement(element.id)));
      const removed = new Set(elements.map((element) => element.id));
      setWorkspace((current) => current ? {
        ...current,
        elements: current.elements.filter((element) => !removed.has(element.id)),
      } : current);
      setSelectedIds([]);
    } else {
      await Promise.all(elements.map(updateWorkspaceElement));
      setWorkspace((current) => {
        if (!current) return current;
        const present = new Set(current.elements.map((element) => element.id));
        return {
          ...current,
          elements: [...current.elements, ...cloneElements(elements).filter((item) => !present.has(item.id))],
        };
      });
    }
  }

  async function undo() {
    const entry = undoStack.at(-1);
    if (!entry) return;
    try {
      await applyHistory(entry, true);
      setUndoStack((current) => current.slice(0, -1));
      setRedoStack((current) => [...current, entry]);
      setStatus("已撤销");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "撤销失败");
    }
  }

  async function redo() {
    const entry = redoStack.at(-1);
    if (!entry) return;
    try {
      await applyHistory(entry, false);
      setRedoStack((current) => current.slice(0, -1));
      setUndoStack((current) => [...current, entry]);
      setStatus("已重做");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "重做失败");
    }
  }

  function defaultElement(
    elementType: WorkspaceElement["element_type"],
    x: number,
    y: number,
    content = "",
  ): Omit<WorkspaceElement, "id"> {
    const top = Math.max(0, ...workspace?.elements.map((element) => element.z_index) ?? [0]);
    const isLine = elementType === "line" || elementType === "arrow";
    const isText = elementType === "text";
    return {
      element_type: elementType,
      x,
      y,
      width: elementType === "image" ? 360 : isLine ? 260 : isText ? 300 : 220,
      height: elementType === "image" ? 240 : isLine ? 24 : isText ? 160 : 150,
      rotation: 0,
      content,
      text_color: "#1F3633",
      fill_color: isLine || elementType === "image" ? "transparent" : isText ? "#FFFEF7" : "#E3F0ED",
      border_color: "#315F59",
      border_width: isLine ? 3 : 2,
      font_size: 18,
      font_family: "Microsoft YaHei",
      text_align: "left",
      z_index: top + 1,
      group_id: null,
    };
  }

  async function createElement(payload: Omit<WorkspaceElement, "id">) {
    try {
      const result = await addWorkspaceElement(libraryId, payload);
      const element = { ...payload, id: result.id };
      setWorkspace((current) => current ? {
        ...current,
        elements: [...current.elements, element],
      } : current);
      setSelectedIds([element.id]);
      record({ kind: "add", before: [], after: [cloneElements([element])[0]] });
      setTool("select");
      setStatus("画布对象已添加");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "画布对象添加失败");
    }
  }

  function canvasClick(event: React.MouseEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return;
    if (tool === "select") {
      setSelectedIds([]);
      return;
    }
    if (tool === "image") {
      imageInput.current?.click();
      return;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, (event.clientX - bounds.left) / zoom);
    const y = Math.max(0, (event.clientY - bounds.top) / zoom);
    void createElement(defaultElement(tool, x, y));
  }

  function uploadImage(file: File | undefined) {
    if (!file) return;
    if (!IMAGE_TYPES.has(file.type) || file.size > 5 * 1024 * 1024) {
      setStatus("仅支持不超过 5 MB 的 PNG、JPEG、WebP 或 GIF 图片");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") return;
      const y = 80 + (document.querySelector(".workspace-scroll")?.scrollTop ?? 0) / zoom;
      void createElement(defaultElement("image", 140, y, reader.result));
    };
    reader.onerror = () => setStatus("图片读取失败");
    reader.readAsDataURL(file);
  }

  function selectionFor(element: WorkspaceElement, shiftKey: boolean): number[] {
    if (!workspace) return [element.id];
    const grouped = element.group_id
      ? workspace.elements.filter((item) => item.group_id === element.group_id).map((item) => item.id)
      : [element.id];
    if (shiftKey) {
      const next = new Set(selectedIds);
      for (const id of grouped) {
        if (next.has(id)) next.delete(id); else next.add(id);
      }
      return [...next];
    }
    if (selectedIds.includes(element.id)) return selectedIds;
    return grouped;
  }

  function beginElementTransform(
    event: React.PointerEvent,
    mode: ElementTransform["mode"],
    element: WorkspaceElement,
  ) {
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const ids = mode === "move" ? selectionFor(element, event.shiftKey) : [element.id];
    setSelectedIds(ids);
    const originals = cloneElements(
      workspace?.elements.filter((item) => ids.includes(item.id)) ?? [element],
    );
    const centerX = element.x + element.width / 2;
    const centerY = element.y + element.height / 2;
    transform.current = {
      mode,
      startX: event.clientX,
      startY: event.clientY,
      originals,
      targetId: element.id,
      centerX,
      centerY,
      startAngle: Math.atan2(event.clientY / zoom - centerY, event.clientX / zoom - centerX),
    };
  }

  function beginLegacyDrag(
    event: React.PointerEvent,
    kind: LegacyDrag["kind"],
    mode: LegacyDrag["mode"],
    id: number,
    x: number,
    y: number,
    width: number,
    height: number,
  ) {
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    legacyDrag.current = {
      kind, mode, id, startX: event.clientX, startY: event.clientY,
      originX: x, originY: y, originWidth: width, originHeight: height,
    };
  }

  function pointerMove(event: React.PointerEvent) {
    if (!workspace) return;
    const activeTransform = transform.current;
    if (activeTransform) {
      const dx = (event.clientX - activeTransform.startX) / zoom;
      const dy = (event.clientY - activeTransform.startY) / zoom;
      const changed = activeTransform.originals.map((element) => {
        if (activeTransform.mode === "move") {
          return { ...element, x: Math.max(0, element.x + dx), y: Math.max(0, element.y + dy) };
        }
        if (element.id !== activeTransform.targetId) return element;
        if (activeTransform.mode === "resize") {
          return {
            ...element,
            width: Math.max(20, element.width + dx),
            height: Math.max(4, element.height + dy),
          };
        }
        const angle = Math.atan2(
          event.clientY / zoom - activeTransform.centerY,
          event.clientX / zoom - activeTransform.centerX,
        );
        return { ...element, rotation: element.rotation + (angle - activeTransform.startAngle) * 180 / Math.PI };
      });
      mergeElements(changed);
      return;
    }
    const active = legacyDrag.current;
    if (!active) return;
    const dx = (event.clientX - active.startX) / zoom;
    const dy = (event.clientY - active.startY) / zoom;
    if (active.kind === "note") {
      setWorkspace({
        ...workspace,
        note_x: active.mode === "move" ? Math.max(0, active.originX + dx) : workspace.note_x,
        note_y: active.mode === "move" ? Math.max(0, active.originY + dy) : workspace.note_y,
        note_width: active.mode === "resize" ? Math.max(280, active.originWidth + dx) : workspace.note_width,
        note_height: active.mode === "resize" ? Math.max(180, active.originHeight + dy) : workspace.note_height,
      });
    } else {
      setWorkspace({
        ...workspace,
        cards: workspace.cards.map((card) => card.id === active.id ? {
          ...card,
          x: active.mode === "move" ? Math.max(0, active.originX + dx) : card.x,
          y: active.mode === "move" ? Math.max(0, active.originY + dy) : card.y,
          width: active.mode === "resize" ? Math.max(280, active.originWidth + dx) : card.width,
          height: active.mode === "resize" ? Math.max(220, active.originHeight + dy) : card.height,
        } : card),
      });
    }
  }

  function pointerUp() {
    if (!workspace) return;
    const activeTransform = transform.current;
    transform.current = null;
    if (activeTransform) {
      const after = cloneElements(
        workspace.elements.filter((element) => activeTransform.originals.some((item) => item.id === element.id)),
      );
      void persistUpdate(activeTransform.originals, after, "对象变换已保存");
      return;
    }
    const active = legacyDrag.current;
    legacyDrag.current = null;
    if (!active) return;
    if (active.kind === "note") {
      void saveLibraryWorkspace(libraryId, workspace).then((result) => {
        setWorkspace((current) => current ? { ...current, version: result.version } : current);
        setStatus("总笔记布局已保存");
      });
    } else {
      const card = workspace.cards.find((item) => item.id === active.id);
      if (card) void updateWorkspaceCard(card.id, card).then(() => setStatus("文章卡片布局已保存"));
    }
  }

  function selectedElements(): WorkspaceElement[] {
    return workspace?.elements.filter((element) => selectedIds.includes(element.id)) ?? [];
  }

  async function changeSelected(
    mutate: (element: WorkspaceElement, index: number, selected: WorkspaceElement[]) => WorkspaceElement,
    message: string,
  ) {
    const before = cloneElements(selectedElements());
    if (!before.length) return;
    const after = before.map((element, index) => mutate(element, index, before));
    mergeElements(after);
    try {
      await persistUpdate(before, after, message);
    } catch (error) {
      mergeElements(before);
      setStatus(error instanceof Error ? error.message : "对象更新失败");
    }
  }

  function copySelection() {
    const selected = cloneElements(selectedElements());
    if (!selected.length) return;
    setClipboard(selected);
    setStatus(`已复制 ${selected.length} 个对象`);
  }

  async function pasteSelection() {
    if (!clipboard.length) return;
    const pasted: WorkspaceElement[] = [];
    const groupMap = new Map<string, string>();
    for (const source of clipboard) {
      const groupId = source.group_id
        ? (groupMap.get(source.group_id) ?? `group-${Date.now()}-${groupMap.size}`)
        : null;
      if (source.group_id && groupId) groupMap.set(source.group_id, groupId);
      const payload = { ...elementWithoutId(source), x: source.x + 28, y: source.y + 28, group_id: groupId };
      const result = await addWorkspaceElement(libraryId, payload);
      pasted.push({ ...payload, id: result.id });
    }
    setWorkspace((current) => current ? { ...current, elements: [...current.elements, ...pasted] } : current);
    setSelectedIds(pasted.map((element) => element.id));
    record({ kind: "add", before: [], after: cloneElements(pasted) });
    setClipboard(cloneElements(pasted));
    setStatus(`已粘贴 ${pasted.length} 个对象`);
  }

  async function removeSelected() {
    const removed = cloneElements(selectedElements());
    if (!removed.length) return;
    await Promise.all(removed.map((element) => deleteWorkspaceElement(element.id)));
    const ids = new Set(removed.map((element) => element.id));
    setWorkspace((current) => current ? {
      ...current,
      elements: current.elements.filter((element) => !ids.has(element.id)),
    } : current);
    setSelectedIds([]);
    record({ kind: "delete", before: removed, after: [] });
    setStatus(`已删除 ${removed.length} 个对象`);
  }

  function groupSelected() {
    if (selectedIds.length < 2) return;
    const groupId = `group-${Date.now()}-${selectedIds.join("-")}`;
    void changeSelected((element) => ({ ...element, group_id: groupId }), "对象已组合");
  }

  function ungroupSelected() {
    void changeSelected((element) => ({ ...element, group_id: null }), "对象已取消组合");
  }

  function layer(front: boolean) {
    const values = workspace?.elements.map((element) => element.z_index) ?? [0];
    const edge = front ? Math.max(0, ...values) + 1 : Math.min(0, ...values) - selectedIds.length;
    void changeSelected(
      (element, index) => ({ ...element, z_index: edge + (front ? index : -index) }),
      front ? "对象已置于顶层" : "对象已置于底层",
    );
  }

  function align(mode: string) {
    const selected = selectedElements();
    if (selected.length < 2) return;
    const left = Math.min(...selected.map((item) => item.x));
    const right = Math.max(...selected.map((item) => item.x + item.width));
    const top = Math.min(...selected.map((item) => item.y));
    const bottom = Math.max(...selected.map((item) => item.y + item.height));
    if (mode === "distribute-x" && selected.length >= 3) {
      const sorted = [...selected].sort((a, b) => a.x - b.x);
      const gap = (right - left - sorted.reduce((sum, item) => sum + item.width, 0)) / (sorted.length - 1);
      const positions = new Map<number, number>();
      let cursor = left;
      for (const item of sorted) { positions.set(item.id, cursor); cursor += item.width + gap; }
      void changeSelected((element) => ({ ...element, x: positions.get(element.id) ?? element.x }), "对象已水平分布");
      return;
    }
    if (mode === "distribute-y" && selected.length >= 3) {
      const sorted = [...selected].sort((a, b) => a.y - b.y);
      const gap = (bottom - top - sorted.reduce((sum, item) => sum + item.height, 0)) / (sorted.length - 1);
      const positions = new Map<number, number>();
      let cursor = top;
      for (const item of sorted) { positions.set(item.id, cursor); cursor += item.height + gap; }
      void changeSelected((element) => ({ ...element, y: positions.get(element.id) ?? element.y }), "对象已垂直分布");
      return;
    }
    void changeSelected((element) => {
      if (mode === "left") return { ...element, x: left };
      if (mode === "center") return { ...element, x: (left + right - element.width) / 2 };
      if (mode === "right") return { ...element, x: right - element.width };
      if (mode === "top") return { ...element, y: top };
      if (mode === "middle") return { ...element, y: (top + bottom - element.height) / 2 };
      return { ...element, y: bottom - element.height };
    }, "对象已对齐");
  }

  function beginEdit(element: WorkspaceElement) {
    if (!editStart.current.has(element.id)) editStart.current.set(element.id, { ...element });
    setSelectedIds([element.id]);
  }

  function editContent(elementId: number, content: string) {
    setWorkspace((current) => current ? {
      ...current,
      elements: current.elements.map((element) => element.id === elementId ? { ...element, content } : element),
    } : current);
  }

  function finishEdit(element: WorkspaceElement) {
    const before = editStart.current.get(element.id);
    editStart.current.delete(element.id);
    if (before) void persistUpdate([before], [{ ...element }], "文字已保存");
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
    canvasHeight,
    workspace.note_y + workspace.note_height + 180,
    ...workspace.cards.map((card) => card.y + card.height + 180),
    ...workspace.elements.map((element) => element.y + element.height + 180),
  );
  const primary = selectedElements()[0];

  function elementStyle(element: WorkspaceElement): CSSProperties {
    const isConnector = element.element_type === "line" || element.element_type === "arrow";
    return {
      left: element.x,
      top: element.y,
      width: element.width,
      height: element.height,
      transform: `rotate(${element.rotation}deg)`,
      zIndex: element.z_index,
      color: isConnector ? element.border_color : element.text_color,
      backgroundColor: element.fill_color,
      borderColor: element.border_color,
      borderWidth: element.border_width,
      fontSize: element.font_size,
      fontFamily: element.font_family,
      textAlign: element.text_align,
    };
  }

  function renderElement(element: WorkspaceElement) {
    const selected = selectedIds.includes(element.id);
    const common = {
      className: `workspace-ppt-element element-${element.element_type} ${selected ? "selected" : ""}`,
      style: elementStyle(element),
      onPointerDown: (event: React.PointerEvent) => beginElementTransform(event, "move", element),
      onClick: (event: React.MouseEvent) => event.stopPropagation(),
    };
    let content: React.ReactNode;
    if (element.element_type === "line" || element.element_type === "arrow") {
      content = <svg viewBox={`0 0 ${element.width} ${element.height}`} preserveAspectRatio="none" aria-hidden="true">
        <defs><marker id={`arrow-${element.id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" /></marker></defs>
        <line x1="3" y1={element.height / 2} x2={element.width - 5} y2={element.height / 2} stroke="currentColor" strokeWidth={element.border_width} markerEnd={element.element_type === "arrow" ? `url(#arrow-${element.id})` : undefined} />
      </svg>;
    } else if (element.element_type === "image") {
      content = <img src={element.content} alt="画布图片" draggable={false} />;
    } else {
      content = <textarea
        aria-label={`编辑${element.element_type === "text" ? "文字" : "形状"} ${element.id}`}
        value={element.content}
        placeholder={element.element_type === "text" ? "输入文字…" : "可在形状中输入文字"}
        onPointerDown={(event) => { event.stopPropagation(); beginEdit(element); }}
        onFocus={() => beginEdit(element)}
        onChange={(event) => { beginEdit(element); editContent(element.id, event.target.value); }}
        onBlur={() => finishEdit(workspace?.elements.find((item) => item.id === element.id) ?? element)}
      />;
    }
    return <div key={element.id} {...common} aria-label={`画布对象 ${element.id}`}>
      {content}
      {selected && <>
        <button type="button" className="element-move-handle" aria-label={`移动对象 ${element.id}`} onPointerDown={(event) => beginElementTransform(event, "move", element)}>✥</button>
        <button type="button" className="element-rotate-handle" aria-label={`旋转对象 ${element.id}`} onPointerDown={(event) => beginElementTransform(event, "rotate", element)}>↻</button>
        <button type="button" className="element-resize-handle" aria-label={`缩放对象 ${element.id}`} onPointerDown={(event) => beginElementTransform(event, "resize", element)} />
      </>}
    </div>;
  }

  return <section className="knowledge-workspace">
    <div className="workspace-actions">
      <select ref={paperSelect} aria-label="选择要加入总笔记的文章" value={paperId} onChange={(event) => setPaperId(event.target.value)}>
        <option value="">选择文章卡片…</option>
        {available.map((paper) => <option key={paper.id} value={paper.id}>{paper.title}</option>)}
      </select>
      <button className="primary-button" type="button" disabled={!paperId} onClick={() => void addCard()}>加入文章卡片</button>
      <span role="status">{status}</span>
    </div>
    <div className="workspace-board ppt-workspace">
      <aside className="workspace-toolbox" aria-label="PPT 画布工具栏">
        <strong>插入</strong>
        {([
          ["select", "↖", "选择或移动"], ["text", "T", "文字"],
          ["rectangle", "□", "矩形"], ["ellipse", "○", "圆形"],
          ["line", "／", "直线"], ["arrow", "→", "箭头"],
        ] as const).map(([value, icon, label]) => <button key={value} type="button" aria-label={value === "select" ? label : `添加${label}`} className={tool === value ? "active" : ""} aria-pressed={tool === value} onClick={() => setTool(value)}><span>{icon}</span>{label}</button>)}
        <button type="button" aria-label="添加图片" className={tool === "image" ? "active" : ""} onClick={() => imageInput.current?.click()}><span>▧</span>图片</button>
        <button type="button" aria-label="添加文章卡片" onClick={() => paperSelect.current?.focus()}><span>▤</span>文章</button>
        <input ref={imageInput} className="visually-hidden" aria-label="选择画布图片" type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => { uploadImage(event.target.files?.[0]); event.target.value = ""; }} />
        <strong>编辑</strong>
        <button type="button" aria-label="撤销" disabled={!undoStack.length} onClick={() => void undo()}><span>↶</span>撤销</button>
        <button type="button" aria-label="重做" disabled={!redoStack.length} onClick={() => void redo()}><span>↷</span>重做</button>
        <button type="button" aria-label="复制" disabled={!selectedIds.length} onClick={copySelection}><span>⧉</span>复制</button>
        <button type="button" aria-label="粘贴" disabled={!clipboard.length} onClick={() => void pasteSelection()}><span>▣</span>粘贴</button>
        <button type="button" aria-label="删除选中" disabled={!selectedIds.length} onClick={() => void removeSelected()}><span>×</span>删除</button>
      </aside>
      <div className="workspace-stage">
        <div className="ppt-commandbar" aria-label="PPT 排版工具">
          <button type="button" disabled={selectedIds.length < 2} onClick={groupSelected}>组合</button>
          <button type="button" disabled={!primary?.group_id} onClick={ungroupSelected}>取消组合</button>
          <button type="button" disabled={!selectedIds.length} onClick={() => layer(true)}>置于顶层</button>
          <button type="button" disabled={!selectedIds.length} onClick={() => layer(false)}>置于底层</button>
          <select aria-label="对齐与分布" value="" disabled={selectedIds.length < 2} onChange={(event) => { if (event.target.value) align(event.target.value); }}>
            <option value="">对齐/分布</option><option value="left">左对齐</option><option value="center">水平居中</option><option value="right">右对齐</option><option value="top">顶端对齐</option><option value="middle">垂直居中</option><option value="bottom">底端对齐</option><option value="distribute-x">水平分布</option><option value="distribute-y">垂直分布</option>
          </select>
          <span className="zoom-control"><button type="button" aria-label="缩小画布" onClick={() => setZoom((value) => Math.max(.5, value - .1))}>−</button><output>{Math.round(zoom * 100)}%</output><button type="button" aria-label="放大画布" onClick={() => setZoom((value) => Math.min(2, value + .1))}>＋</button></span>
        </div>
        {primary && <div className="ppt-formatbar" aria-label="对象格式">
          <label>字体<select aria-label="字体" value={primary.font_family} onChange={(event) => void changeSelected((element) => ({ ...element, font_family: event.target.value }), "字体已更新")}>{FONT_FAMILIES.map((font) => <option key={font}>{font}</option>)}</select></label>
          <label>字号<input aria-label="字号" type="number" min="8" max="400" value={primary.font_size} onChange={(event) => void changeSelected((element) => ({ ...element, font_size: Number(event.target.value) }), "字号已更新")} /></label>
          <label>文字<input aria-label="文字颜色" type="color" value={primary.text_color} onChange={(event) => void changeSelected((element) => ({ ...element, text_color: event.target.value }), "文字颜色已更新")} /></label>
          <label>填充<input aria-label="填充颜色" type="color" value={primary.fill_color === "transparent" ? "#FFFFFF" : primary.fill_color} onChange={(event) => void changeSelected((element) => ({ ...element, fill_color: event.target.value }), "填充颜色已更新")} /></label>
          <label>边框<input aria-label="边框颜色" type="color" value={primary.border_color} onChange={(event) => void changeSelected((element) => ({ ...element, border_color: event.target.value }), "边框颜色已更新")} /></label>
          <label>线宽<input aria-label="边框宽度" type="number" min="0" max="100" value={primary.border_width} onChange={(event) => void changeSelected((element) => ({ ...element, border_width: Number(event.target.value) }), "边框宽度已更新")} /></label>
          <label>对齐<select aria-label="文字对齐" value={primary.text_align} onChange={(event) => void changeSelected((element) => ({ ...element, text_align: event.target.value as WorkspaceElement["text_align"] }), "文字对齐已更新")}><option value="left">左</option><option value="center">中</option><option value="right">右</option></select></label>
        </div>}
        <div className="workspace-scroll" onScroll={(event) => { const node = event.currentTarget; if (node.scrollTop + node.clientHeight >= node.scrollHeight - 180) setCanvasHeight((value) => value + 700); }}>
          <div className={`workspace-canvas tool-${tool}`} style={{ minHeight: extent, zoom }} onClick={canvasClick} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
            <article className="workspace-note" style={{ left: workspace.note_x, top: workspace.note_y, width: workspace.note_width, height: workspace.note_height }}>
              <header onPointerDown={(event) => beginLegacyDrag(event, "note", "move", 0, workspace.note_x, workspace.note_y, workspace.note_width, workspace.note_height)}>总笔记 <span>拖动排布</span></header>
              <textarea aria-label="总笔记" value={workspace.body} onChange={(event) => { setWorkspace({ ...workspace, body: event.target.value }); setDirty(true); setStatus("等待保存…"); }} placeholder="在这里汇总思路、结论和研究脉络…" />
              <button type="button" className="legacy-resize-handle" aria-label="缩放总笔记" onPointerDown={(event) => beginLegacyDrag(event, "note", "resize", 0, workspace.note_x, workspace.note_y, workspace.note_width, workspace.note_height)} />
            </article>
            {workspace.elements.map(renderElement)}
            {workspace.cards.map((card) => <article className="workspace-paper-card" key={card.id} style={{ left: card.x, top: card.y, width: card.width, height: card.height }}>
              <header onPointerDown={(event) => beginLegacyDrag(event, "card", "move", card.id, card.x, card.y, card.width, card.height)}><span>文章卡片 · 拖动排布</span><button type="button" aria-label={`移除 ${card.title}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => void deleteWorkspaceCard(card.id).then(reload)}>×</button></header>
              <div className="workspace-card-scroll"><h2>{card.title}</h2>{card.title_translation && <p className="card-translation">{card.title_translation}</p>}<button type="button" onClick={() => void translate(card, "title")}>翻译题目</button><h3>摘要</h3><p>{card.abstract || "暂无摘要"}</p>{card.abstract_translation && <p className="card-translation">{card.abstract_translation}</p>}<button type="button" disabled={!card.abstract} onClick={() => void translate(card, "abstract")}>翻译摘要</button><h3>文章笔记汇总</h3>{card.notes.length ? card.notes.map((note) => <blockquote key={note.id}>{note.body}</blockquote>) : <p>暂无文章笔记</p>}{card.file_id && <a className="reader-link" href={`#reader?paper=${card.paper_id}&file=${card.file_id}`}>阅读并翻译 PDF</a>}</div>
              <button type="button" className="legacy-resize-handle" aria-label={`缩放文章卡片 ${card.title}`} onPointerDown={(event) => beginLegacyDrag(event, "card", "resize", card.id, card.x, card.y, card.width, card.height)} />
            </article>)}
          </div>
        </div>
      </div>
    </div>
  </section>;
}
