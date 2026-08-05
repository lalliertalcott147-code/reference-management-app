import { useState } from "react";
import {
  type ImportPreview,
  type ImportReport,
  confirmWosImport,
  previewWosImport,
} from "../api";

type ImportState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "preview"; data: ImportPreview }
  | { kind: "complete"; data: ImportReport }
  | { kind: "error"; message: string };

export function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<ImportState>({ kind: "idle" });

  async function preview(selected: File) {
    setFile(selected);
    setState({ kind: "loading" });
    try {
      setState({ kind: "preview", data: await previewWosImport(selected) });
    } catch (error) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "无法读取导出文件" });
    }
  }

  async function confirm() {
    if (!file) return;
    setState({ kind: "loading" });
    try {
      setState({ kind: "complete", data: await confirmWosImport(file) });
    } catch (error) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "导入失败" });
    }
  }

  return <div className="page import-page">
    <header className="page-header"><div><p className="eyebrow">人工增强通道</p><h1>导入 WoS 官方记录</h1></div><a className="secondary-button" href="https://www.webofscience.com" target="_blank" rel="noreferrer">打开 Web of Science</a></header>
    <div className="guide-card">
      <span className="step-number">1</span><div><strong>由你本人登录和导出</strong><p>在学校正常入口登录 WoS，选择“完整记录”；优先 Plain Text，也支持 RIS 和 Excel。</p></div>
      <span className="step-number">2</span><div><strong>先预览，再写入</strong><p>App 不保存账号、密码、Cookie 或导出原文件，只解析你选择的文件。</p></div>
    </div>
    <label className="drop-zone">
      <input type="file" accept=".txt,.ris,.xlsx" onChange={(event) => { const selected = event.target.files?.[0]; if (selected) void preview(selected); }} />
      <span className="upload-symbol">⇧</span><strong>选择 WoS 导出文件</strong><small>最大 25 MB；会检查真实内容，不只看扩展名</small>
    </label>
    {state.kind === "loading" && <div className="notice" role="status">正在安全解析文件…</div>}
    {state.kind === "error" && <div className="notice error" role="alert"><strong>文件未导入</strong><span>{state.message}</span></div>}
    {state.kind === "preview" && <section className="preview-panel" aria-labelledby="preview-title"><h2 id="preview-title">导入预览</h2>
      <div className="metric-grid"><div><strong>{state.data.total}</strong><span>有效记录</span></div><div><strong>{state.data.new}</strong><span>新增</span></div><div><strong>{state.data.duplicates}</strong><span>重复</span></div><div><strong>{state.data.missing_doi}</strong><span>缺少 DOI</span></div><div><strong>{state.data.conflicts}</strong><span>字段冲突</span></div></div>
      {state.data.issues.length > 0 && <ul className="issue-list">{state.data.issues.map((issue, index) => <li key={index}>记录 {issue.record_number ?? "?"}：{issue.message}</li>)}</ul>}
      <div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => { setFile(null); setState({ kind: "idle" }); }}>取消</button><button className="primary-button" type="button" onClick={() => void confirm()}>确认导入</button></div>
    </section>}
    {state.kind === "complete" && <div className="success-panel" role="status"><h2>导入完成</h2><p>新增 {state.data.added}，更新 {state.data.updated}，跳过重复 {state.data.skipped}，失败 {state.data.failed}。</p><a href="#library" className="primary-button">查看知识库</a></div>}
  </div>;
}
