import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Database,
  Download,
  FileText,
  FileVideo,
  Filter,
  Mic2,
  Play,
  RefreshCw,
  Scissors,
  Sparkles,
  Upload,
  XCircle
} from "lucide-react";
import { api } from "./lib/api";
import type { AnalysisPayload, Clip, Episode } from "./types";

const platforms = [
  ["youtube_shorts", "YouTube Shorts"],
  ["tiktok", "TikTok"],
  ["instagram_reels", "Instagram/Reels"],
  ["linkedin", "LinkedIn"]
];

const emptyContext = {
  icp: "B2B technology leaders, founders, and enterprise product teams",
  target_audience: "Executives evaluating AI, software modernization, and data strategy",
  audience_pain_points: "AI uncertainty, implementation cost, unclear ROI, risk, and speed to market",
  tkxel_services: "AI strategy, product engineering, data platforms, cloud modernization",
  hot_topic: "AI strategy and business impact",
  business_objectives: "Increase BetterTech audience quality and create qualified conversations for TKXEL",
  episode_plan: "",
  preferred_platforms: ["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
  editor_notes: "Keep claims credible, executive-friendly, and specific."
};

export default function App() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedEpisodeId, setSelectedEpisodeId] = useState("");
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClipId, setSelectedClipId] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [createForm, setCreateForm] = useState({
    title: "Dr. Seth Dobrin - Preventing Global Tech Homogenization",
    guest_name: "Dr. Seth Dobrin",
    guest_role: "Founder and CEO",
    guest_company: "Qantm AI",
    theme: "Preventing Global Tech Homogenization",
    recording_date: "2024-11-25"
  });
  const [contextForm, setContextForm] = useState(emptyContext);
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptFile, setTranscriptFile] = useState<File | null>(null);
  const [assetFile, setAssetFile] = useState<File | null>(null);
  const [assetType, setAssetType] = useState("video");
  const [clipTypeFilter, setClipTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisPayload>({
    ai_provider: "azure_openai",
    clip_types: ["short", "highlight"],
    duration_min_seconds: null,
    duration_max_seconds: null,
    target_clip_count: 10,
    platforms: ["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
    custom_instructions: "",
    mode: "mock"
  });

  useEffect(() => {
    loadEpisodes();
  }, []);

  useEffect(() => {
    if (selectedEpisodeId) {
      loadClips();
    }
  }, [selectedEpisodeId, clipTypeFilter, statusFilter]);

  const selectedEpisode = useMemo(
    () => episodes.find((episode) => episode.id === selectedEpisodeId),
    [episodes, selectedEpisodeId]
  );
  const selectedClip = useMemo(
    () => clips.find((clip) => clip.id === selectedClipId) ?? clips[0],
    [clips, selectedClipId]
  );

  async function run<T>(label: string, action: () => Promise<T>, done?: (result: T) => void) {
    setBusy(label);
    setMessage("");
    try {
      const result = await action();
      done?.(result);
      setMessage(`${label} complete`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Something went wrong");
    } finally {
      setBusy("");
    }
  }

  async function loadEpisodes() {
    const data = await api.episodes();
    setEpisodes(data);
    if (!selectedEpisodeId && data[0]) {
      setSelectedEpisodeId(data[0].id);
    }
  }

  async function loadClips() {
    if (!selectedEpisodeId) return;
    const data = await api.clips(selectedEpisodeId, { clip_type: clipTypeFilter, status: statusFilter });
    setClips(data);
    setSelectedClipId((current) => (data.some((clip) => clip.id === current) ? current : data[0]?.id ?? ""));
  }

  function updateAnalysisClipType(type: "short" | "highlight", enabled: boolean) {
    setAnalysis((current) => {
      const clipTypes = enabled
        ? Array.from(new Set([...current.clip_types, type]))
        : current.clip_types.filter((item) => item !== type);
      return { ...current, clip_types: clipTypes.length ? clipTypes : [type] };
    });
  }

  function updatePlatform(platform: string, enabled: boolean) {
    setAnalysis((current) => {
      const selected = enabled
        ? Array.from(new Set([...current.platforms, platform]))
        : current.platforms.filter((item) => item !== platform);
      return { ...current, platforms: selected.length ? selected : [platform] };
    });
  }

  function createEpisode(event: FormEvent) {
    event.preventDefault();
    run("Episode", () => api.createEpisode(createForm), (episode) => {
      setEpisodes((current) => [episode, ...current]);
      setSelectedEpisodeId(episode.id);
    });
  }

  function saveContext(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId) return;
    run("Context", () => api.saveContext(selectedEpisodeId, contextForm));
  }

  function uploadTranscript(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId) return;
    const form = new FormData();
    if (transcriptFile) form.append("file", transcriptFile);
    if (transcriptText.trim()) form.append("content", transcriptText);
    form.append("source_format", transcriptFile ? transcriptFile.name.split(".").pop() ?? "txt" : "txt");
    run("Transcript", () => api.uploadTranscript(selectedEpisodeId, form), () => loadEpisodes());
  }

  function uploadAsset(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId || !assetFile) return;
    const form = new FormData();
    form.append("file", assetFile);
    form.append("asset_type", assetType);
    form.append("is_primary", ["video", "audio"].includes(assetType) ? "true" : "false");
    run("Asset", () => api.uploadAsset(selectedEpisodeId, form), () => loadEpisodes());
  }

  function analyzeEpisode() {
    if (!selectedEpisodeId) return;
    run("Analysis", () => api.analyze(selectedEpisodeId, analysis), () => {
      loadEpisodes();
      loadClips();
    });
  }

  function setClipStatus(clip: Clip, status: string) {
    run(status, () => api.updateClipStatus(clip.id, status), () => loadClips());
  }

  function renderClip(clip: Clip) {
    const renderTypes = clip.clip_type === "short" ? ["original", "vertical"] : ["original"];
    run("Render", () => api.renderClip(clip.id, renderTypes), () => loadClips());
  }

  function exportEpisode() {
    if (!selectedEpisodeId) return;
    run("Export", () => api.exportEpisode(selectedEpisodeId), (pack) => {
      if (pack.status === "completed") {
        window.open(api.downloadExportUrl(pack.id), "_blank");
      }
    });
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Database size={28} />
          <div>
            <strong>AURORA PRISM</strong>
            <span>Podcast intelligence</span>
          </div>
        </div>

        <form className="panel compact" onSubmit={createEpisode}>
          <div className="panel-title">
            <FileText size={18} />
            <h2>Episode</h2>
          </div>
          <input
            value={createForm.title}
            onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })}
            placeholder="Episode title"
          />
          <div className="two-col">
            <input
              value={createForm.guest_name}
              onChange={(event) => setCreateForm({ ...createForm, guest_name: event.target.value })}
              placeholder="Guest"
            />
            <input
              value={createForm.guest_company}
              onChange={(event) => setCreateForm({ ...createForm, guest_company: event.target.value })}
              placeholder="Company"
            />
          </div>
          <input
            value={createForm.theme}
            onChange={(event) => setCreateForm({ ...createForm, theme: event.target.value })}
            placeholder="Theme"
          />
          <button type="submit">
            <Sparkles size={16} />
            Create
          </button>
        </form>

        <section className="episode-list">
          {episodes.map((episode) => (
            <button
              className={`episode-card ${episode.id === selectedEpisodeId ? "active" : ""}`}
              key={episode.id}
              onClick={() => setSelectedEpisodeId(episode.id)}
            >
              <strong>{episode.title}</strong>
              <span>{episode.status}</span>
              <small>
                {episode.clip_count} clips · {episode.asset_count} assets · {episode.transcript_segment_count} segments
              </small>
            </button>
          ))}
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{selectedEpisode?.title ?? "New episode workspace"}</h1>
            <p>{selectedEpisode?.guest_name ?? "Create or select an episode"}</p>
          </div>
          <div className="topbar-actions">
            <button className="ghost" onClick={() => loadEpisodes()}>
              <RefreshCw size={16} />
            </button>
            <button onClick={analyzeEpisode} disabled={!selectedEpisodeId || Boolean(busy)}>
              <Sparkles size={16} />
              Analyze
            </button>
            <button className="secondary" onClick={exportEpisode} disabled={!selectedEpisodeId || Boolean(busy)}>
              <Download size={16} />
              Export
            </button>
          </div>
        </header>

        {message && <div className="status-line">{busy || message}</div>}

        <div className="grid-layout">
          <section className="panel intake">
            <div className="panel-title">
              <Upload size={18} />
              <h2>Intake</h2>
            </div>

            <form className="stack" onSubmit={saveContext}>
              <label>
                ICP
                <textarea
                  value={contextForm.icp}
                  onChange={(event) => setContextForm({ ...contextForm, icp: event.target.value })}
                />
              </label>
              <label>
                Hot topic
                <input
                  value={contextForm.hot_topic}
                  onChange={(event) => setContextForm({ ...contextForm, hot_topic: event.target.value })}
                />
              </label>
              <label>
                TKXEL services
                <textarea
                  value={contextForm.tkxel_services}
                  onChange={(event) => setContextForm({ ...contextForm, tkxel_services: event.target.value })}
                />
              </label>
              <label>
                Episode plan
                <textarea
                  value={contextForm.episode_plan}
                  onChange={(event) => setContextForm({ ...contextForm, episode_plan: event.target.value })}
                />
              </label>
              <button type="submit" disabled={!selectedEpisodeId || Boolean(busy)}>
                <CheckCircle2 size={16} />
                Save Context
              </button>
            </form>

            <form className="upload-row" onSubmit={uploadAsset}>
              <select value={assetType} onChange={(event) => setAssetType(event.target.value)}>
                <option value="video">Video</option>
                <option value="audio">Audio</option>
                <option value="guest_document">Guest document</option>
                <option value="guest_headshot">Guest headshot</option>
                <option value="brand_reference">Brand reference</option>
              </select>
              <input
                type="file"
                onChange={(event) => setAssetFile(event.currentTarget.files?.[0] ?? null)}
              />
              <button type="submit" disabled={!assetFile || !selectedEpisodeId || Boolean(busy)}>
                {assetType === "audio" ? <Mic2 size={16} /> : <FileVideo size={16} />}
                Upload
              </button>
            </form>

            <form className="stack" onSubmit={uploadTranscript}>
              <label>
                Transcript
                <textarea
                  className="transcript-box"
                  value={transcriptText}
                  onChange={(event) => setTranscriptText(event.target.value)}
                  placeholder="Paste timestamped transcript"
                />
              </label>
              <input
                type="file"
                accept=".txt,.vtt,.srt,.csv"
                onChange={(event) => setTranscriptFile(event.currentTarget.files?.[0] ?? null)}
              />
              <button type="submit" disabled={!selectedEpisodeId || Boolean(busy)}>
                <Upload size={16} />
                Save Transcript
              </button>
            </form>
          </section>

          <section className="panel controls">
            <div className="panel-title">
              <Scissors size={18} />
              <h2>Clip Instructions</h2>
            </div>
            <div className="toggle-grid">
              <label>
                <input
                  type="checkbox"
                  checked={analysis.clip_types.includes("short")}
                  onChange={(event) => updateAnalysisClipType("short", event.target.checked)}
                />
                Shorts
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={analysis.clip_types.includes("highlight")}
                  onChange={(event) => updateAnalysisClipType("highlight", event.target.checked)}
                />
                3-6 min highlights
              </label>
            </div>
            <label>
              AI provider
              <select
                value={analysis.ai_provider}
                onChange={(event) =>
                  setAnalysis({ ...analysis, ai_provider: event.target.value as "azure_openai" | "openai" })
                }
              >
                <option value="azure_openai">Azure OpenAI</option>
                <option value="openai">OpenAI</option>
              </select>
            </label>
            <div className="two-col">
              <label>
                Min seconds
                <input
                  type="number"
                  value={analysis.duration_min_seconds ?? ""}
                  onChange={(event) =>
                    setAnalysis({ ...analysis, duration_min_seconds: event.target.value ? Number(event.target.value) : null })
                  }
                />
              </label>
              <label>
                Max seconds
                <input
                  type="number"
                  value={analysis.duration_max_seconds ?? ""}
                  onChange={(event) =>
                    setAnalysis({ ...analysis, duration_max_seconds: event.target.value ? Number(event.target.value) : null })
                  }
                />
              </label>
            </div>
            <label>
              Clip count
              <input
                type="number"
                min={1}
                max={30}
                value={analysis.target_clip_count}
                onChange={(event) => setAnalysis({ ...analysis, target_clip_count: Number(event.target.value) })}
              />
            </label>
            <div className="platforms">
              {platforms.map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={analysis.platforms.includes(key)}
                    onChange={(event) => updatePlatform(key, event.target.checked)}
                  />
                  {label}
                </label>
              ))}
            </div>
            <label>
              Optional direction
              <textarea
                value={analysis.custom_instructions ?? ""}
                onChange={(event) => setAnalysis({ ...analysis, custom_instructions: event.target.value })}
                placeholder="Focus on AI governance, avoid salesy clips"
              />
            </label>
          </section>

          <section className="panel board">
            <div className="board-head">
              <div className="panel-title">
                <Filter size={18} />
                <h2>PRISM Board</h2>
              </div>
              <div className="filters">
                <select value={clipTypeFilter} onChange={(event) => setClipTypeFilter(event.target.value)}>
                  <option value="">All types</option>
                  <option value="short">Shorts</option>
                  <option value="highlight">Highlights</option>
                </select>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="">All statuses</option>
                  <option value="recommended">Recommended</option>
                  <option value="approved">Approved</option>
                  <option value="needs_revision">Needs revision</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
            </div>
            <div className="clip-list">
              {clips.map((clip) => (
                <button
                  key={clip.id}
                  className={`clip-row ${selectedClip?.id === clip.id ? "active" : ""}`}
                  onClick={() => setSelectedClipId(clip.id)}
                >
                  <span className="rank">{clip.rank}</span>
                  <span>
                    <strong>{clip.clip_type}</strong>
                    <small>{formatTime(clip.start_seconds)} · {Math.round(clip.duration_seconds)}s</small>
                  </span>
                  <span className="score">{clip.score?.total_score ?? 0}</span>
                </button>
              ))}
              {!clips.length && <div className="empty">No clips yet</div>}
            </div>
          </section>

          <section className="panel detail">
            {selectedClip ? (
              <>
                <div className="detail-head">
                  <div>
                    <h2>Clip {selectedClip.rank}</h2>
                    <p>
                      {selectedClip.clip_type} · {selectedClip.moment_type.replace("_", " ")} ·{" "}
                      {formatTime(selectedClip.start_seconds)}-{formatTime(selectedClip.end_seconds)}
                    </p>
                  </div>
                  <div className="score-large">{selectedClip.score?.total_score ?? 0}</div>
                </div>
                <p className="excerpt">{selectedClip.excerpt}</p>
                <p className="reasoning">{selectedClip.reasoning}</p>

                <div className="score-grid">
                  {selectedClip.score &&
                    Object.entries(selectedClip.score)
                      .filter(([key, value]) => typeof value === "number" && key !== "total_score")
                      .map(([key, value]) => (
                        <span key={key}>
                          {key.replaceAll("_", " ")}
                          <strong>{value}</strong>
                        </span>
                      ))}
                </div>

                <div className="metadata-tabs">
                  {selectedClip.metadata.map((item) => (
                    <article key={item.platform} className="metadata-card">
                      <strong>{item.platform.replaceAll("_", " ")}</strong>
                      <h3>{item.title}</h3>
                      <p>{item.hook}</p>
                      <small>{item.hashtags.join(" ")}</small>
                    </article>
                  ))}
                </div>

                <div className="actions">
                  <button onClick={() => setClipStatus(selectedClip, "approved")}>
                    <CheckCircle2 size={16} />
                    Approve
                  </button>
                  <button className="secondary" onClick={() => setClipStatus(selectedClip, "needs_revision")}>
                    <RefreshCw size={16} />
                    Revision
                  </button>
                  <button className="danger" onClick={() => setClipStatus(selectedClip, "rejected")}>
                    <XCircle size={16} />
                    Reject
                  </button>
                  <button className="secondary" onClick={() => renderClip(selectedClip)}>
                    <Play size={16} />
                    Render
                  </button>
                </div>

                <div className="render-list">
                  {selectedClip.rendered_clips.map((rendered) => (
                    <a key={rendered.id} href={api.downloadRenderUrl(rendered.id)} target="_blank" rel="noreferrer">
                      {rendered.render_type} · {rendered.status}
                    </a>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty">Select a clip</div>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  return `${minutes}:${sec.toString().padStart(2, "0")}`;
}
