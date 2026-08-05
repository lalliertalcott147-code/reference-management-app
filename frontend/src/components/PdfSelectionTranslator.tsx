import { useState } from "react";
import { appendNote, fetchJob, submitTextTranslation } from "../api";

export interface PdfTranslationSelection {
  page: number;
  text: string;
}

export function PdfSelectionTranslator({
  paperId,
  fileId,
  selection,
}: {
  paperId: number;
  fileId: number;
  selection: PdfTranslationSelection | null;
}) {
  const [translation, setTranslation] = useState<{
    page: number; sourceText: string; translatedText: string;
  } | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const activeTranslation = selection && translation
    && translation.page === selection.page && translation.sourceText === selection.text
    ? translation.translatedText : "";
  const visibleStatus = status || (selection
    ? `已选择第 ${selection.page} 页文本`
    : "拖动或框选 PDF 文本后可翻译");

  async function translate() {
    if (!selection) return;
    setBusy(true);
    setStatus("正在使用本地模型翻译…");
    try {
      const { job_id: jobId } = await submitTextTranslation(paperId, selection.text);
      for (;;) {
        const job = await fetchJob(jobId);
        if (job.status === "completed") {
          setTranslation({
            page: selection.page,
            sourceText: selection.text,
            translatedText: job.result?.translated_text ?? "",
          });
          setStatus("翻译完成");
          break;
        }
        if (job.status === "failed" || job.status === "cancelled") {
          throw new Error(job.error_message ?? "翻译未完成");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 300));
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "翻译失败");
    } finally {
      setBusy(false);
    }
  }

  async function addToNote() {
    if (!selection || !activeTranslation) return;
    const note = `[PDF 第 ${selection.page} 页 · 文件 ${fileId}]\n原文：${selection.text}\n译文：${activeTranslation}`;
    try {
      await appendNote(paperId, note);
      setStatus("原文和译文已添加到文章笔记");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "添加笔记失败");
    }
  }

  return <section className="pdf-translator">
    <h2>划词翻译</h2>
    <button type="button" disabled={!selection || busy} onClick={() => void translate()}>翻译选中文本</button>
    {selection && <p className="pdf-source-text">{selection.text}</p>}
    {activeTranslation && <><h3>译文</h3><p className="pdf-translated-text">{activeTranslation}</p><button type="button" onClick={() => void addToNote()}>添加到文章笔记</button></>}
    <small role="status">{visibleStatus}</small>
  </section>;
}
