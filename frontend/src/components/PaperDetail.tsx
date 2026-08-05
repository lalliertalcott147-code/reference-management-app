import { useEffect, useState } from "react";
import {
  cancelTranslation,
  downloadModel,
  fetchJob,
  fetchModelStatus,
  type JobStatus,
  type MergedPaper,
  type ModelStatus,
  type SourceName,
  submitTranslation,
} from "../api";
import { PdfUpload } from "./PdfUpload";

const sourceLabels: Record<SourceName, string> = {
  wos: "Web of Science",
  openalex: "OpenAlex",
  crossref: "Crossref",
  wos_export: "WoS 官方导入",
  pdf: "本地 PDF",
};

interface Props {
  paper: MergedPaper;
  onClose: () => void;
  ensureSaved: () => Promise<number | null>;
}

type Field = "title" | "abstract";

export function PaperDetail({ paper, onClose, ensureSaved }: Props) {
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [jobs, setJobs] = useState<Partial<Record<Field, JobStatus>>>({});
  const [message, setMessage] = useState("");
  const conflicts = Object.entries(paper.provenance)
    .filter(([, values]) => values.length > 1);

  useEffect(() => {
    void fetchModelStatus().then(setModel).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "无法读取翻译模型状态");
    });
  }, []);

  async function waitForJob(field: Field, jobId: number) {
    for (;;) {
      const job = await fetchJob(jobId);
      setJobs((current) => ({ ...current, [field]: job }));
      if (["completed", "failed", "cancelled"].includes(job.status)) return;
      await new Promise((resolve) => window.setTimeout(resolve, 350));
    }
  }

  async function translate(field: Field) {
    setMessage("");
    if (model?.state !== "ready") {
      setMessage("请先安装并校验本地翻译模型");
      return;
    }
    const paperId = await ensureSaved();
    if (paperId === null) return;
    try {
      const { job_id: jobId } = await submitTranslation(paperId, field, true, true);
      setJobs((current) => ({ ...current, [field]: {
        id: jobId, kind: "translation", status: "pending", progress_current: 0,
        progress_total: null, result: null, error_code: null, error_message: null,
      } }));
      await waitForJob(field, jobId);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "翻译失败，原文没有改动");
    }
  }

  async function installModel() {
    const confirmed = window.confirm("将从腾讯官方 Hugging Face 仓库下载约 1.13 GB 模型，是否继续？");
    if (!confirmed) return;
    try {
      const { job_id: jobId } = await downloadModel(true);
      for (;;) {
        const job = await fetchJob(jobId);
        setMessage(job.status === "failed" ? (job.error_message ?? "模型下载失败") : `模型下载：${job.progress_current} / ${job.progress_total ?? "?"} 字节`);
        if (["completed", "failed"].includes(job.status)) break;
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
      setModel(await fetchModelStatus());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "模型下载失败");
    }
  }

  async function cancel(field: Field) {
    const job = jobs[field];
    if (job) await cancelTranslation(job.id);
  }

  function translationPanel(field: Field) {
    const job = jobs[field];
    if (job?.status === "completed" && job.result?.translated_text) {
      return <div className="translation-result"><p>{job.result.translated_text}</p><button type="button" onClick={() => void translate(field)}>重新翻译</button></div>;
    }
    if (job?.status === "failed" || job?.status === "cancelled") {
      return <div className="empty-inline">{job.status === "cancelled" ? "翻译已取消，原文保持不变。" : (job.error_message ?? "翻译失败，原文保持不变。")} <button type="button" onClick={() => void translate(field)}>重试</button></div>;
    }
    if (job && ["pending", "running", "cancelling"].includes(job.status)) {
      return <div className="translation-progress" role="status"><span>本机翻译中 {job.progress_total ? `${job.progress_current}/${job.progress_total}` : "…"}</span><button type="button" onClick={() => void cancel(field)}>取消</button></div>;
    }
    return <div className="empty-inline">尚未翻译。<button type="button" onClick={() => void translate(field)}>在本机翻译并保存</button></div>;
  }
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="paper-detail-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="icon-button close" type="button" onClick={onClose} aria-label="关闭详情">×</button>
        <p className="eyebrow">文献详情</p>
        <h2 id="paper-detail-title">{paper.title}</h2>
        <h3>题名译文</h3>
        {translationPanel("title")}
        <p className="paper-authors">{paper.authors.join("；") || "作者信息暂缺"}</p>
        <div className="metadata-row">
          <span>{paper.journal ?? "期刊暂缺"}</span><span>{paper.year ?? "年份暂缺"}</span>
          {paper.doi && <span>DOI {paper.doi}</span>}
        </div>
        <PdfUpload ensurePaperId={ensureSaved} />
        <h3>摘要原文</h3>
        <p className="abstract-full">{paper.abstract ?? "当前开放来源未提供摘要。可导入 WoS 完整记录或上传 PDF 补充。"}</p>
        <h3>中文译文</h3>
        {paper.abstract ? translationPanel("abstract") : <div className="empty-inline">没有摘要原文，无法翻译。</div>}
        {model?.state !== "ready" && <div className="model-missing"><strong>本地翻译模型未安装</strong><span>Hy-MT2-1.8B Q4_K_M · 约 1.13 GB · Apache-2.0</span><button type="button" onClick={() => void installModel()}>确认并下载模型</button></div>}
        {message && <p className="translation-message" role="status">{message}</p>}
        <h3>数据来源</h3>
        <div className="source-list">
          {paper.sources.map((source) => (
            <div key={`${source.source}-${source.source_id}`}>
              <strong>{sourceLabels[source.source]}</strong>
              <span>{source.source_id}</span>
              {source.url && <a href={source.url} target="_blank" rel="noreferrer">打开原始记录</a>}
            </div>
          ))}
        </div>
        {conflicts.length > 0 && <>
          <h3>来源差异</h3>
          <ul className="conflict-list">
            {conflicts.map(([field, values]) => <li key={field}>{field} 有 {values.length} 个来源值，当前按来源优先级展示。</li>)}
          </ul>
        </>}
      </section>
    </div>
  );
}
