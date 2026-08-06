import { useEffect, useMemo, useRef, useState } from "react";
import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentProxy,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import {
  createPdfAnnotation,
  deletePdfAnnotation,
  fetchPdfAnnotations,
  fetchPdfPages,
  fetchPdfPosition,
  savePdfPosition,
  type PdfAnnotation,
  type PdfPageData,
  updatePdfAnnotation,
} from "../api";
import { PdfSelectionTranslator } from "../components/PdfSelectionTranslator";

GlobalWorkerOptions.workerSrc = workerUrl;
type PdfOutline = NonNullable<Awaited<ReturnType<PDFDocumentProxy["getOutline"]>>>;

interface SelectionData {
  page: number;
  text: string;
  prefix: string;
  suffix: string;
  rects: { x: number; y: number; width: number; height: number }[];
}

interface PageProps {
  document: PDFDocumentProxy;
  number: number;
  scale: number;
  metadata?: PdfPageData;
  annotations: PdfAnnotation[];
  onVisible: (page: number) => void;
  onSelect: (selection: SelectionData) => void;
}

function PdfPageView(props: PageProps) {
  const wrapper = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const text = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(props.number <= 2);
  const width = (props.metadata?.width ?? 612) * props.scale;
  const height = (props.metadata?.height ?? 792) * props.scale;

  useEffect(() => {
    const element = wrapper.current;
    if (!element) return;
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          setActive(true);
          props.onVisible(props.number);
        } else if (Math.abs(entry.boundingClientRect.top) > window.innerHeight * 2) {
          setActive(false);
        }
      }
    }, { rootMargin: "600px 0px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [props]);

  useEffect(() => {
    const canvasElement = canvas.current;
    const textElement = text.current;
    if (!active || !canvasElement || !textElement) return;
    let cancelled = false;
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]> | null = null;
    let layer: TextLayer | null = null;
    void props.document.getPage(props.number).then(async (page) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale: props.scale });
      const ratio = window.devicePixelRatio || 1;
      canvasElement.width = Math.floor(viewport.width * ratio);
      canvasElement.height = Math.floor(viewport.height * ratio);
      canvasElement.style.width = `${viewport.width}px`;
      canvasElement.style.height = `${viewport.height}px`;
      const context = canvasElement.getContext("2d");
      if (!context) return;
      renderTask = page.render({
        canvas: canvasElement,
        canvasContext: context,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      await renderTask.promise;
      if (cancelled) return;
      textElement.replaceChildren();
      if (props.metadata?.source === "ocr") {
        for (const block of props.metadata.blocks) {
          const polygon = block.polygon;
          if (!polygon?.length) continue;
          const xs = polygon.map((point) => point[0]);
          const ys = polygon.map((point) => point[1]);
          const span = document.createElement("span");
          span.textContent = block.text;
          span.style.left = `${Math.min(...xs) * 100}%`;
          span.style.top = `${Math.min(...ys) * 100}%`;
          span.style.width = `${(Math.max(...xs) - Math.min(...xs)) * 100}%`;
          span.style.height = `${(Math.max(...ys) - Math.min(...ys)) * 100}%`;
          textElement.append(span);
        }
      } else {
        layer = new TextLayer({
          textContentSource: page.streamTextContent(),
          container: textElement,
          viewport,
        });
        await layer.render();
      }
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
      layer?.cancel();
      canvasElement.width = 0;
      canvasElement.height = 0;
      textElement.replaceChildren();
    };
  }, [active, props.document, props.metadata, props.number, props.scale]);

  function selected() {
    const selection = window.getSelection();
    const element = wrapper.current;
    if (!selection || selection.isCollapsed || !element || !selection.toString().trim()) return;
    const range = selection.getRangeAt(0);
    if (!element.contains(range.commonAncestorContainer)) return;
    const bounds = element.getBoundingClientRect();
    const rects = [...range.getClientRects()].map((rect) => ({
      x: Math.max(0, (rect.left - bounds.left) / bounds.width),
      y: Math.max(0, (rect.top - bounds.top) / bounds.height),
      width: Math.min(1, rect.width / bounds.width),
      height: Math.min(1, rect.height / bounds.height),
    })).filter((rect) => rect.width > 0 && rect.height > 0);
    if (!rects.length) return;
    const selectedText = selection.toString().trim();
    const content = props.metadata?.content ?? "";
    const index = content.indexOf(selectedText);
    props.onSelect({
      page: props.number,
      text: selectedText,
      prefix: index < 0 ? "" : content.slice(Math.max(0, index - 120), index),
      suffix: index < 0 ? "" : content.slice(index + selectedText.length, index + selectedText.length + 120),
      rects,
    });
  }

  return <div ref={wrapper} className="pdf-page" data-page={props.number} style={{ width, height }} onMouseUp={selected}>
    {active && <><canvas ref={canvas} /><div ref={text} className="textLayer" />{props.annotations.filter((item) => !item.is_stale).flatMap((item) => item.rects.map((rect, index) => <span key={`${item.id}-${index}`} className={`annotation-overlay ${item.annotation_type}`} style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%`, backgroundColor: item.annotation_type === "highlight" ? item.color : undefined, borderBottomColor: item.color }} title={item.comment_text || item.selected_text} />))}</>}
    <small className="page-number">{props.number}</small>
  </div>;
}

function PdfThumbnail({
  document,
  number,
  current,
  onClick,
}: {
  document: PDFDocumentProxy;
  number: number;
  current: boolean;
  onClick: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    if (!element || !current) return;
    let cancelled = false;
    void document.getPage(number).then(async (page) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale: .2 });
      element.width = viewport.width;
      element.height = viewport.height;
      const context = element.getContext("2d");
      if (context) await page.render({ canvas: element, canvasContext: context, viewport }).promise;
    });
    return () => { cancelled = true; element.width = 0; element.height = 0; };
  }, [current, document, number]);
  return <button className={current ? "active thumbnail" : "thumbnail"} type="button" onClick={onClick}>{current ? <canvas ref={canvas} /> : <span>{number}</span>}<small>第 {number} 页</small></button>;
}

function readerParameters() {
  const query = new URLSearchParams(location.hash.split("?")[1] ?? "");
  return {
    paperId: Number(query.get("paper")),
    fileId: Number(query.get("file")),
    targetPage: Number(query.get("page")) || null,
  };
}

export function PdfReaderPage() {
  const { paperId, fileId, targetPage } = readerParameters();
  const scroll = useRef<HTMLDivElement>(null);
  const [pdfDocument, setPdfDocument] = useState<PDFDocumentProxy | null>(null);
  const [pages, setPages] = useState<PdfPageData[]>([]);
  const [annotations, setAnnotations] = useState<PdfAnnotation[]>([]);
  const [current, setCurrent] = useState(1);
  const [scale, setScale] = useState(1.15);
  const [selection, setSelection] = useState<SelectionData | null>(null);
  const [search, setSearch] = useState("");
  const [annotationFilter, setAnnotationFilter] = useState("");
  const [message, setMessage] = useState("正在打开本机 PDF…");
  const [outline, setOutline] = useState<PdfOutline>([]);
  const [scrollOffset, setScrollOffset] = useState(0);

  useEffect(() => {
    const loading = getDocument({ url: `/api/pdfs/${fileId}/content` });
    void Promise.all([
      loading.promise,
      fetchPdfPages(fileId),
      fetchPdfPosition(fileId, paperId),
      fetchPdfAnnotations(fileId, paperId),
    ]).then(([nextDocument, nextPages, position, nextAnnotations]) => {
      setPdfDocument(nextDocument); setPages(nextPages); setScale(position.scale);
      const initialPage = targetPage ?? position.page_number;
      setCurrent(initialPage); setAnnotations(nextAnnotations); setMessage("");
      setScrollOffset(position.scroll_offset);
      void nextDocument.getOutline().then((items) => setOutline(items ?? []));
      window.setTimeout(() => {
        if (targetPage) {
          window.document.querySelector(`[data-page="${targetPage}"]`)?.scrollIntoView();
        } else if (scroll.current) {
          scroll.current.scrollTop = position.scroll_offset;
        }
      }, 0);
    }).catch((error: unknown) => setMessage(error instanceof Error ? error.message : "PDF 打开失败"));
    return () => { void loading.destroy(); };
  }, [fileId, paperId, targetPage]);

  useEffect(() => {
    if (!pdfDocument) return;
    const timer = window.setTimeout(() => {
      void savePdfPosition(fileId, paperId, current, scale, scrollOffset);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [current, fileId, paperId, pdfDocument, scale, scrollOffset]);

  const matchingPages = useMemo(() => search.trim() ? pages.filter((page) => page.content.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())).map((page) => page.page_number) : [], [pages, search]);
  const thumbnailPages = useMemo(() => {
    if (!pdfDocument) return [];
    const visible = new Set([1, pdfDocument.numPages]);
    for (let page = Math.max(1, current - 10); page <= Math.min(pdfDocument.numPages, current + 10); page += 1) visible.add(page);
    return [...visible].sort((left, right) => left - right);
  }, [current, pdfDocument]);

  async function refreshAnnotations() {
    setAnnotations(await fetchPdfAnnotations(fileId, paperId, annotationFilter));
  }

  async function annotate(type: PdfAnnotation["annotation_type"]) {
    if (!selection) return;
    const comment = type === "comment" ? (window.prompt("输入批注内容") ?? "") : "";
    await createPdfAnnotation(fileId, {
      paper_id: paperId, annotation_type: type, page_number: selection.page,
      color: type === "underline" ? "#16776D" : "#F4D35E",
      selected_text: selection.text, prefix_text: selection.prefix,
      suffix_text: selection.suffix, rects: selection.rects, comment_text: comment,
    });
    window.getSelection()?.removeAllRanges(); setSelection(null); await refreshAnnotations();
    setMessage("批注已同时保存为知识笔记");
  }

  function jump(page: number) {
    window.document.querySelector(`[data-page="${page}"]`)?.scrollIntoView({ behavior: "smooth" });
    setCurrent(page);
  }

  async function jumpOutline(item: PdfOutline[number]) {
    if (!pdfDocument || !item.dest) return;
    const destination = typeof item.dest === "string"
      ? await pdfDocument.getDestination(item.dest)
      : item.dest;
    if (!destination?.[0]) return;
    const reference = destination[0] as Parameters<PDFDocumentProxy["getPageIndex"]>[0];
    const index = await pdfDocument.getPageIndex(reference);
    jump(index + 1);
  }

  if (!paperId || !fileId) return <div className="page"><div className="notice error">阅读链接无效</div></div>;
  return <div className="reader-shell">
    <header className="reader-toolbar"><a href="#library">← 知识库</a><button type="button" onClick={() => setScale((value) => Math.max(.5, value - .15))}>−</button><span>{Math.round(scale * 100)}%</span><button type="button" onClick={() => setScale((value) => Math.min(3, value + .15))}>＋</button><button type="button" onClick={() => setScale(1.15)}>适宽</button><button type="button" onClick={() => setScale(.85)}>适页</button><label>页码 <input type="number" min="1" max={pdfDocument?.numPages ?? 1} value={current} onChange={(event) => jump(Number(event.target.value))} /></label><span>/ {pdfDocument?.numPages ?? "?"}</span><button type="button" disabled={!selection} onClick={() => void annotate("highlight")}>高亮</button><button type="button" disabled={!selection} onClick={() => void annotate("underline")}>划线</button><button type="button" disabled={!selection} onClick={() => void annotate("comment")}>批注</button><span role="status">{message}</span></header>
    <aside className="reader-sidebar"><PdfSelectionTranslator paperId={paperId} fileId={fileId} selection={selection} /><h2>全文搜索</h2><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索 PDF 文本" />{matchingPages.map((page) => <button key={page} type="button" onClick={() => jump(page)}>第 {page} 页匹配</button>)}{outline.length > 0 && <><h2>目录</h2>{outline.map((item, index) => <button key={`${item.title}-${index}`} type="button" onClick={() => void jumpOutline(item)}>{item.title}</button>)}</>}<h2>缩略图</h2><div className="thumbnail-list">{pdfDocument && thumbnailPages.map((page) => <PdfThumbnail key={page} document={pdfDocument} number={page} current={Math.abs(current - page) <= 2} onClick={() => jump(page)} />)}</div><h2>批注</h2><select value={annotationFilter} onChange={(event) => { setAnnotationFilter(event.target.value); void fetchPdfAnnotations(fileId, paperId, event.target.value).then(setAnnotations); }}><option value="">全部</option><option value="highlight">高亮</option><option value="underline">划线</option><option value="comment">批注</option></select>{annotations.map((item) => <div className="annotation-list-item" key={item.id}><button type="button" onClick={() => jump(item.page_number)}>第 {item.page_number} 页 · {item.annotation_type}</button><p>{item.selected_text}</p>{item.comment_text && <p>{item.comment_text}</p>}<button type="button" onClick={() => { const edited = window.prompt("编辑批注", item.comment_text); if (edited !== null) void updatePdfAnnotation(item.id, { comment_text: edited }).then(refreshAnnotations); }}>编辑</button><button type="button" onClick={() => void deletePdfAnnotation(item.id).then(refreshAnnotations)}>删除</button>{item.is_stale && <strong>定位已失效</strong>}</div>)}</aside>
    <main ref={scroll} className="pdf-scroll" onScroll={(event) => setScrollOffset(event.currentTarget.scrollTop)}>{pdfDocument && Array.from({ length: pdfDocument.numPages }, (_, index) => <PdfPageView key={index + 1} document={pdfDocument} number={index + 1} scale={scale} metadata={pages.find((item) => item.page_number === index + 1)} annotations={annotations.filter((item) => item.page_number === index + 1)} onVisible={setCurrent} onSelect={setSelection} />)}</main>
  </div>;
}
