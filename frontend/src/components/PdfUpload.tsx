import { useRef, useState } from "react";
import {
  applyPdfMetadata,
  confirmPdf,
  fetchJob,
  type PdfPreview,
  previewPdf,
} from "../api";

interface Props {
  paperId?: number;
  ensurePaperId?: () => Promise<number | null>;
  compact?: boolean;
  onComplete?: (paperId: number, fileId: number) => void;
}

export function PdfUpload({ paperId, ensurePaperId, compact = false, onComplete }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [targetPaper, setTargetPaper] = useState(paperId);
  const [preview, setPreview] = useState<PdfPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [values, setValues] = useState<Record<string, string>>( {} );

  async function choose(file: File) {
    setBusy(true); setMessage("正在校验并检查重复…");
    try {
      const resolvedPaper = targetPaper ?? await ensurePaperId?.() ?? undefined;
      if (ensurePaperId && resolvedPaper === undefined) return;
      setTargetPaper(resolvedPaper);
      const result = await previewPdf(file, resolvedPaper);
      setPreview(result);
      setValues(Object.fromEntries(result.preview.candidates.map((item) => [item.field_name, item.value])));
      setMessage(result.preview.duplicate_level === "none" ? "校验通过，请核对元数据" : "检测到可能重复，请明确选择处理方式");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "PDF 校验失败");
    } finally {
      setBusy(false);
    }
  }

  async function commit(resolution: "attach" | "link_existing" | "keep_version") {
    if (!preview) return;
    setBusy(true); setMessage("正在永久保存并逐页识别…");
    try {
      const firstMatch = preview.preview.matches[0];
      const result = await confirmPdf({
        upload_token: preview.token,
        paper_id: targetPaper,
        resolution,
        matched_paper_id: resolution === "link_existing" ? firstMatch?.paper_id : undefined,
      });
      for (;;) {
        const job = await fetchJob(result.job_id);
        if (job.status === "failed") throw new Error(job.error_message ?? "PDF 处理失败");
        if (job.status === "completed") break;
        await new Promise((resolve) => window.setTimeout(resolve, 350));
      }
      const authors = values.authors?.split(/[,;；]/).map((item) => item.trim()).filter(Boolean);
      await applyPdfMetadata(result.file_id, {
        paper_id: result.paper_id,
        title: values.title || undefined,
        abstract: values.abstract || undefined,
        doi: values.doi || undefined,
        authors: authors?.length ? authors : undefined,
        year: values.year ? Number(values.year) : undefined,
      });
      setMessage(result.deduplicated ? "已关联本机已有 PDF，不增加物理副本" : "PDF 已永久保存并完成识别");
      setPreview(null);
      onComplete?.(result.paper_id, result.file_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "PDF 入库失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (preview) {
      try {
        await confirmPdf({ upload_token: preview.token, resolution: "cancel" });
      } catch {
        // The server may report an already expired session; local UI can still close it.
      }
    }
    setPreview(null); setMessage("");
  }

  return <div className={`pdf-upload ${compact ? "compact" : ""}`}>
    <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void choose(file); event.target.value = ""; }} />
    <button className={compact ? "" : "secondary-button"} type="button" disabled={busy} onClick={() => input.current?.click()}>{busy ? "处理中…" : "上传 PDF"}</button>
    {message && <span className="pdf-message" role="status">{message}</span>}
    {preview && <div className="pdf-confirm" role="dialog" aria-label="核对 PDF 入库">
      <h3>{preview.original_name}</h3><p>{preview.page_count} 页 · {(preview.size_bytes / 1024 / 1024).toFixed(1)} MB · SHA-256 已计算</p>
      {preview.preview.duplicate_level !== "none" && <div className="notice"><strong>{preview.preview.duplicate_level === "exact" ? "文件内容完全相同" : preview.preview.duplicate_level === "doi" ? "发现同 DOI 文献或版本" : "发现题名相似文献"}</strong><span>不会静默覆盖，请选择关联或保留为版本。</span></div>}
      <div className="metadata-editor">
        {(["title", "authors", "year", "doi", "abstract"] as const).map((field) => <label key={field}>{({ title: "题名", authors: "作者", year: "年份", doi: "DOI", abstract: "摘要" })[field]}{field === "abstract" ? <textarea value={values[field] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))} /> : <input value={values[field] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))} />}</label>)}
      </div>
      <div className="dialog-actions"><button type="button" onClick={() => void cancel()}>取消</button>{preview.preview.duplicate_level !== "none" && <button type="button" onClick={() => void commit("link_existing")}>关联已有记录</button>}{preview.preview.duplicate_level !== "none" && preview.preview.duplicate_level !== "exact" && <button type="button" onClick={() => void commit("keep_version")}>保留为新版本</button>}{preview.preview.duplicate_level === "none" && <button className="primary-button" type="button" onClick={() => void commit("attach")}>确认入库</button>}</div>
    </div>}
  </div>;
}
