import { type FormEvent, useEffect, useState } from "react";
import {
  addGlossaryTerm,
  addInterestTerm,
  deleteInterestTerm,
  deleteResearchTopic,
  deleteGlossaryTerm,
  fetchGlossary,
  fetchInterestTerms,
  fetchModelStatus,
  fetchResearchTopics,
  type GlossaryTerm,
  type InterestTerm,
  type ModelStatus,
  type ResearchTopic,
  type SettingsResponse,
  saveResearchTopic,
  updateSettings,
} from "../api";

interface Props {
  settings: SettingsResponse;
  onChange: (settings: SettingsResponse) => void;
}

export function SettingsPage({ settings, onChange }: Props) {
  const [wosKey, setWosKey] = useState("");
  const [openAlexKey, setOpenAlexKey] = useState("");
  const [email, setEmail] = useState(settings.crossref_email ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [term, setTerm] = useState("");
  const [mapped, setMapped] = useState("");
  const [termType, setTermType] = useState<GlossaryTerm["term_type"]>("glossary");
  const [topics, setTopics] = useState<ResearchTopic[]>([]);
  const [interestTerms, setInterestTerms] = useState<InterestTerm[]>([]);
  const [topicName, setTopicName] = useState("");
  const [topicQuery, setTopicQuery] = useState("");
  const [interestTerm, setInterestTerm] = useState("");
  const [interestType, setInterestType] = useState<InterestTerm["term_type"]>("positive");
  const [dailyLimit, setDailyLimit] = useState(settings.automatic_search_daily_limit);

  useEffect(() => {
    void Promise.all([
      fetchModelStatus(), fetchGlossary(), fetchResearchTopics(), fetchInterestTerms(),
    ]).then(([nextModel, nextTerms, nextTopics, nextInterestTerms]) => {
      setModel(nextModel);
      setTerms(nextTerms);
      setTopics(nextTopics);
      setInterestTerms(nextInterestTerms);
    }).catch((error: unknown) => setMessage(error instanceof Error ? error.message : "读取本地翻译设置失败"));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const updated = await updateSettings({
        wos_api_key: wosKey || null,
        openalex_api_key: openAlexKey || null,
        crossref_email: email,
        personalization_enabled: settings.personalization_enabled,
        automatic_search_daily_limit: dailyLimit,
      });
      onChange(updated);
      setWosKey(""); setOpenAlexKey("");
      setMessage("设置已安全保存到本机");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function addTopic(event: FormEvent) {
    event.preventDefault();
    await saveResearchTopic({ name: topicName, query_text: topicQuery, enabled: true });
    setTopics(await fetchResearchTopics());
    setTopicName("");
    setTopicQuery("");
    setMessage("研究主题已保存，推荐会显示具体命中原因。");
  }

  async function addPreferenceTerm(event: FormEvent) {
    event.preventDefault();
    await addInterestTerm(interestTerm, interestType);
    setInterestTerms(await fetchInterestTerms());
    setInterestTerm("");
    setMessage("关键词偏好已保存到本机。");
  }

  async function addTerm(event: FormEvent) {
    event.preventDefault();
    try {
      await addGlossaryTerm(term, termType === "glossary" ? mapped : null, termType);
      setTerms(await fetchGlossary());
      setTerm(""); setMapped("");
      setMessage("术语已保存，后续翻译会使用新版本");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "术语保存失败");
    }
  }

  return <div className="page settings-page"><header className="page-header"><div><p className="eyebrow">本机设置</p><h1>设置</h1></div></header>
    <form className="settings-form" onSubmit={(event) => void submit(event)}>
      <section className="settings-card"><h2>免费检索服务</h2><p>密钥通过 Windows DPAPI 加密，浏览器只看到掩码。</p>
        <label>Web of Science Starter API Key<span>{settings.wos_api_key ? `已保存 ${settings.wos_api_key}` : "未配置"}</span><input type="password" autoComplete="off" value={wosKey} onChange={(event) => setWosKey(event.target.value)} placeholder="输入新的 Key（留空则不改）" /></label>
        <label>OpenAlex 免费 API Key<span>{settings.openalex_api_key ? `已保存 ${settings.openalex_api_key}` : "未配置"}</span><input type="password" autoComplete="off" value={openAlexKey} onChange={(event) => setOpenAlexKey(event.target.value)} placeholder="输入新的免费 Key（留空则不改）" /></label>
        <label>Crossref 联系邮箱<span>用于 polite pool，不是账号</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.edu" /></label>
      </section>
      <section className="settings-card"><h2>本地存储</h2><dl><div><dt>数据目录</dt><dd>{settings.storage}</dd></div><div><dt>可删除缓存上限</dt><dd>{settings.cache_limit_mb} MB</dd></div><div><dt>PDF 与模型</dt><dd>永久资料，不计入缓存</dd></div></dl></section>
      <section className="settings-card"><h2>本地翻译</h2><p>腾讯 Hy-MT2-1.8B Q4_K_M，约 1.13 GB，Apache-2.0；只翻译题名和摘要，首次翻译时按需启动。</p><dl><div><dt>模型状态</dt><dd>{model?.state === "ready" ? (model.running ? "已安装 · 正在运行" : "已安装 · 当前未运行") : model?.state === "invalid" ? "校验失败，需要重新下载" : "未安装"}</dd></div></dl>
        <div className="glossary-list">{terms.map((item) => <div key={item.id}><span><strong>{item.term}</strong>{item.term_type === "glossary" ? ` → ${item.mapped_term}` : " · 保持原文"}</span><button type="button" onClick={() => void deleteGlossaryTerm(item.id).then(() => fetchGlossary()).then(setTerms)}>删除</button></div>)}</div>
        <div className="glossary-editor"><select value={termType} onChange={(event) => setTermType(event.target.value as GlossaryTerm["term_type"])}><option value="glossary">固定译法</option><option value="do_not_translate">保持原文</option></select><input aria-label="原文术语" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="英文术语" />{termType === "glossary" && <input aria-label="中文译法" value={mapped} onChange={(event) => setMapped(event.target.value)} placeholder="中文译法" />}<button className="secondary-button" type="button" onClick={(event) => void addTerm(event)}>添加术语</button></div>
      </section>
      <section className="settings-card"><h2>推荐行为</h2><label className="toggle-row"><span><strong>使用阅读行为优化本地推荐</strong><small>关闭后仅使用你主动设置的主题和期刊</small></span><input type="checkbox" checked={settings.personalization_enabled} onChange={(event) => onChange({ ...settings, personalization_enabled: event.target.checked })} /></label></section>
      <section className="settings-card"><h2>研究主题与关键词</h2><p>这些规则只在本机与文献元数据匹配，不会上传笔记或 PDF 正文。</p>
        <div className="preference-list">{topics.map((item) => <div key={item.id}><span><strong>{item.name}</strong><small>{item.query_text}</small></span><label><input type="checkbox" checked={item.enabled} onChange={(event) => void saveResearchTopic({ name: item.name, query_text: item.query_text, enabled: event.target.checked }, item.id).then(fetchResearchTopics).then(setTopics)} /> 启用</label><button type="button" onClick={() => void deleteResearchTopic(item.id).then(fetchResearchTopics).then(setTopics)}>删除</button></div>)}</div>
        <div className="glossary-editor"><input aria-label="研究主题名称" value={topicName} onChange={(event) => setTopicName(event.target.value)} placeholder="例如 光催化" /><input aria-label="研究主题检索词" value={topicQuery} onChange={(event) => setTopicQuery(event.target.value)} placeholder="photocatalysis CO2" /><button className="secondary-button" type="button" disabled={!topicName.trim() || !topicQuery.trim()} onClick={(event) => void addTopic(event)}>添加主题</button></div>
        <div className="preference-list">{interestTerms.map((item) => <div key={item.id}><span><strong>{item.term}</strong><small>{item.term_type === "positive" ? "优先推荐" : "降低推荐"}</small></span><button type="button" onClick={() => void deleteInterestTerm(item.id).then(fetchInterestTerms).then(setInterestTerms)}>删除</button></div>)}</div>
        <div className="glossary-editor"><select value={interestType} onChange={(event) => setInterestType(event.target.value as InterestTerm["term_type"])}><option value="positive">关注关键词</option><option value="negative">排除关键词</option></select><input aria-label="推荐关键词" value={interestTerm} onChange={(event) => setInterestTerm(event.target.value)} placeholder="关键词" /><button className="secondary-button" type="button" disabled={!interestTerm.trim()} onClick={(event) => void addPreferenceTerm(event)}>添加关键词</button></div>
      </section>
      <section className="settings-card"><h2>免费额度保护</h2><label>每天最多自动检查次数<span>每次检查可能调用多个已配置的免费来源；达到上限后等到第二天。</span><input type="number" min="1" max="50" value={dailyLimit} onChange={(event) => setDailyLimit(Number(event.target.value))} /></label></section>
      <div className="save-row"><button className="primary-button" type="submit" disabled={saving}>{saving ? "保存中…" : "保存设置"}</button><span role="status">{message}</span></div>
    </form>
  </div>;
}
