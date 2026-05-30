import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  FileVideo,
  Filter,
  KeyRound,
  Layers3,
  LockKeyhole,
  LogOut,
  Mic2,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Radio,
  RefreshCw,
  Save,
  Scissors,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  WandSparkles,
  XCircle
} from "lucide-react";
import aidxLogo from "./assets/aidx-logo.png";
import { ApiError, api } from "./lib/api";
import type { AnalysisPayload, AnalysisRun, AuthSession, Clip, Episode, EpisodeEvent, RenderedClip } from "./types";

const EVENT_HISTORY_LIMIT = 30;
const AUTH_STORAGE_KEY = "aurora-prism:auth-session";
const MIN_SIGNUP_PASSWORD_LENGTH = 8;
const APP_PATH = "/app";
const LOGIN_PATH = "/auth/login";
const SIGNUP_PATH = "/auth/signup";

const platforms = [
  ["youtube_shorts", "YouTube Shorts"],
  ["tiktok", "TikTok"],
  ["instagram_reels", "Instagram/Reels"],
  ["linkedin", "LinkedIn"]
];

const renderOptions = [
  ["original", "Original"],
  ["vertical", "Vertical"],
  ["audio", "Audio"],
  ["waveform", "Waveform"]
];

const modeLabels: Record<AnalysisPayload["mode"], string> = {
  hybrid: "Hybrid LLM",
  openai: "LLM only",
  mock: "Mock heuristic"
};

const statusActionLabels: Record<string, string> = {
  approved: "Approve clip",
  needs_revision: "Send to revision",
  rejected: "Reject clip"
};

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
  const [authSession, setAuthSession] = useState<AuthSession | null>(() => readStoredAuthSession());
  const [authChecked, setAuthChecked] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "signup">(() => initialAuthMode());
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [signupForm, setSignupForm] = useState({
    username: "",
    display_name: "",
    password: "",
    confirmPassword: ""
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsForm, setSettingsForm] = useState({
    username: "",
    display_name: "",
    currentPassword: "",
    newPassword: "",
    confirmPassword: ""
  });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [settingsTone, setSettingsTone] = useState<"success" | "error">("success");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [episodeDetailsOpen, setEpisodeDetailsOpen] = useState(false);
  const [episodeDetailsBusy, setEpisodeDetailsBusy] = useState(false);
  const [episodeDetailsMessage, setEpisodeDetailsMessage] = useState("");
  const [episodeDetailsTone, setEpisodeDetailsTone] = useState<"success" | "error">("success");
  const [episodeDetailsForm, setEpisodeDetailsForm] = useState({
    title: "",
    guest_name: "",
    guest_role: "",
    guest_company: "",
    theme: "",
    recording_date: ""
  });
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedEpisodeId, setSelectedEpisodeId] = useState("");
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClipId, setSelectedClipId] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"info" | "success" | "error">("info");
  const [episodeEvents, setEpisodeEvents] = useState<EpisodeEvent[]>([]);
  const [reviewerName, setReviewerName] = useState("AURORA Demo");
  const [createForm, setCreateForm] = useState({
    title: "",
    guest_name: "",
    guest_role: "",
    guest_company: "",
    theme: "",
    recording_date: ""
  });
  const [contextForm, setContextForm] = useState(emptyContext);
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptFile, setTranscriptFile] = useState<File | null>(null);
  const [assetFile, setAssetFile] = useState<File | null>(null);
  const [assetType, setAssetType] = useState("video");
  const [renderTypes, setRenderTypes] = useState<string[]>(["original", "vertical"]);
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
    mode: "hybrid"
  });

  useEffect(() => {
    if (!authSession) {
      api.setAuthToken("");
      setAuthChecked(true);
      return;
    }

    let active = true;
    api.setAuthToken(authSession.access_token);
    setReviewerName(authSession.user.display_name);
    setAuthChecked(false);
    api.me()
      .then((user) => {
        if (!active) return;
        const verifiedSession = { ...authSession, user };
        storeAuthSession(verifiedSession);
        setAuthSession(verifiedSession);
        setReviewerName(user.display_name);
        setAuthChecked(true);
        loadEpisodes();
      })
      .catch((error) => {
        if (!active) return;
        handleAuthFailure(error);
        setAuthChecked(true);
      });

    return () => {
      active = false;
    };
  }, [authSession?.access_token]);

  useEffect(() => {
    if (!authChecked) return;
    if (authSession) {
      if (isAuthPath()) replaceBrowserPath(APP_PATH);
      return;
    }
    replaceBrowserPath(authMode === "signup" ? SIGNUP_PATH : LOGIN_PATH);
  }, [authChecked, authSession?.access_token, authMode]);

  useEffect(() => {
    if (!authSession) return;
    setSettingsForm((current) => ({
      ...current,
      username: authSession.user.username,
      display_name: authSession.user.display_name
    }));
  }, [authSession?.user.id, authSession?.user.username, authSession?.user.display_name]);

  useEffect(() => {
    if (authSession && selectedEpisodeId) {
      loadClips();
    }
  }, [authSession?.access_token, selectedEpisodeId, clipTypeFilter, statusFilter]);

  useEffect(() => {
    if (!authSession || !selectedEpisodeId) {
      setEpisodeEvents([]);
      return;
    }

    setEpisodeEvents(readStoredEpisodeEvents(selectedEpisodeId));
    const source = new EventSource(api.episodeEventsUrl(selectedEpisodeId));
    source.addEventListener("episode", (event) => {
      try {
        const parsed = JSON.parse(event.data) as EpisodeEvent;
        setEpisodeEvents((current) => {
          const next = mergeEpisodeEvent(current, parsed);
          storeEpisodeEvents(selectedEpisodeId, next);
          return next;
        });
      } catch {
        // Ignore malformed SSE payloads without interrupting the workspace.
      }
    });

    return () => source.close();
  }, [authSession?.access_token, selectedEpisodeId]);

  const selectedEpisode = useMemo(
    () => episodes.find((episode) => episode.id === selectedEpisodeId),
    [episodes, selectedEpisodeId]
  );
  useEffect(() => {
    if (!selectedEpisode) return;
    setEpisodeDetailsForm({
      title: selectedEpisode.title,
      guest_name: selectedEpisode.guest_name ?? "",
      guest_role: selectedEpisode.guest_role ?? "",
      guest_company: selectedEpisode.guest_company ?? "",
      theme: selectedEpisode.theme ?? "",
      recording_date: selectedEpisode.recording_date ?? ""
    });
    setEpisodeDetailsMessage("");
  }, [selectedEpisode?.id]);
  const selectedClip = useMemo(
    () => clips.find((clip) => clip.id === selectedClipId) ?? clips[0],
    [clips, selectedClipId]
  );
  const approvedCount = clips.filter((clip) => clip.status === "approved").length;
  const recommendedCount = clips.filter((clip) => clip.status === "recommended").length;
  const latestEvent = episodeEvents[0] ?? null;
  const currentEvent = latestEvent && !isCompletedEpisodeEvent(latestEvent) ? latestEvent : null;
  const currentEventProgress = currentEvent ? eventProgress(currentEvent) : null;
  const transcriptReady = Boolean(selectedEpisode?.transcript_segment_count);
  const hasMediaAsset = Boolean(selectedEpisode?.media_asset_count);
  const canAnalyze = Boolean(selectedEpisodeId && transcriptReady && !busy);
  const canUploadTranscript = Boolean(selectedEpisodeId && !busy && (transcriptFile || transcriptText.trim()));

  async function login(event: FormEvent) {
    event.preventDefault();
    setLoggingIn(true);
    setLoginError("");
    try {
      const session = await api.login(loginForm);
      applyAuthSession(session);
      setLoginForm((current) => ({ ...current, password: "" }));
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Unable to sign in");
    } finally {
      setLoggingIn(false);
    }
  }

  async function signup(event: FormEvent) {
    event.preventDefault();
    setLoggingIn(true);
    setLoginError("");
    if (signupForm.password !== signupForm.confirmPassword) {
      setLoginError("Passwords do not match");
      setLoggingIn(false);
      return;
    }
    if (signupForm.password.length < MIN_SIGNUP_PASSWORD_LENGTH) {
      setLoginError(`Password must be at least ${MIN_SIGNUP_PASSWORD_LENGTH} characters.`);
      setLoggingIn(false);
      return;
    }
    try {
      const session = await api.signup({
        username: signupForm.username.trim(),
        display_name: signupForm.display_name.trim(),
        password: signupForm.password
      });
      applyAuthSession(session);
      setSignupForm({ username: "", display_name: "", password: "", confirmPassword: "" });
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Unable to create account");
    } finally {
      setLoggingIn(false);
    }
  }

  function applyAuthSession(session: AuthSession) {
    api.setAuthToken(session.access_token);
    storeAuthSession(session);
    setAuthSession(session);
    setReviewerName(session.user.display_name);
  }

  function openSettings() {
    if (!authSession) return;
    setSettingsForm({
      username: authSession.user.username,
      display_name: authSession.user.display_name,
      currentPassword: "",
      newPassword: "",
      confirmPassword: ""
    });
    setSettingsMessage("");
    setSettingsOpen(true);
  }

  function openEpisodeDetails() {
    if (!selectedEpisode) return;
    setEpisodeDetailsForm({
      title: selectedEpisode.title,
      guest_name: selectedEpisode.guest_name ?? "",
      guest_role: selectedEpisode.guest_role ?? "",
      guest_company: selectedEpisode.guest_company ?? "",
      theme: selectedEpisode.theme ?? "",
      recording_date: selectedEpisode.recording_date ?? ""
    });
    setEpisodeDetailsTone("success");
    setEpisodeDetailsMessage("");
    setEpisodeDetailsOpen(true);
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    setSettingsBusy(true);
    setSettingsMessage("");
    if (settingsForm.newPassword || settingsForm.currentPassword || settingsForm.confirmPassword) {
      if (!settingsForm.currentPassword) {
        setSettingsTone("error");
        setSettingsMessage("Current password is required.");
        setSettingsBusy(false);
        return;
      }
      if (settingsForm.newPassword.length < MIN_SIGNUP_PASSWORD_LENGTH) {
        setSettingsTone("error");
        setSettingsMessage(`New password must be at least ${MIN_SIGNUP_PASSWORD_LENGTH} characters.`);
        setSettingsBusy(false);
        return;
      }
      if (settingsForm.newPassword !== settingsForm.confirmPassword) {
        setSettingsTone("error");
        setSettingsMessage("New passwords do not match.");
        setSettingsBusy(false);
        return;
      }
    }

    try {
      const session = await api.updateProfile({
        username: settingsForm.username.trim(),
        display_name: settingsForm.display_name.trim(),
        ...(settingsForm.newPassword
          ? {
              current_password: settingsForm.currentPassword,
              new_password: settingsForm.newPassword
            }
          : {})
      });
      applyAuthSession(session);
      setSettingsForm((current) => ({
        ...current,
        currentPassword: "",
        newPassword: "",
        confirmPassword: ""
      }));
      setSettingsTone("success");
      setSettingsMessage("Settings saved.");
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setSettingsTone("error");
      setSettingsMessage(error instanceof Error ? error.message : "Unable to save settings");
    } finally {
      setSettingsBusy(false);
    }
  }

  async function logout() {
    try {
      await api.logout();
    } catch {
      // The local session should still be cleared if the server token has expired.
    } finally {
      clearSessionState();
      setLoginError("");
    }
  }

  function handleAuthFailure(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      clearSessionState();
      setLoginError("Your session expired. Sign in again.");
      return true;
    }
    return false;
  }

  function clearSessionState() {
    api.setAuthToken("");
    clearStoredAuthSession();
    setAuthSession(null);
    setEpisodes([]);
    setSelectedEpisodeId("");
    setClips([]);
    setSelectedClipId("");
    setEpisodeEvents([]);
    setBusy("");
    setMessage("");
  }

  async function run<T>(label: string, action: () => Promise<T>, done?: (result: T) => void | Promise<void>) {
    setBusy(label);
    setMessage(`${label} running`);
    setMessageTone("info");
    try {
      const result = await action();
      await done?.(result);
      setMessage(`${label} complete`);
      setMessageTone("success");
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setMessage(error instanceof Error ? error.message : "Something went wrong");
      setMessageTone("error");
    } finally {
      setBusy("");
    }
  }

  async function loadEpisodes() {
    try {
      const data = await api.episodes();
      setEpisodes(data);
      setSelectedEpisodeId((current) =>
        current && data.some((episode) => episode.id === current) ? current : data[0]?.id ?? ""
      );
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setMessage(error instanceof Error ? error.message : "Unable to load episodes");
      setMessageTone("error");
    }
  }

  function mergeEpisode(updatedEpisode: Episode) {
    setEpisodes((current) =>
      current.map((episode) => (episode.id === updatedEpisode.id ? updatedEpisode : episode))
    );
  }

  async function deleteEpisode(episode: Episode) {
    const confirmed = window.confirm(
      `Delete "${episode.title}" from history? This removes its clips, transcripts, assets, and exports.`
    );
    if (!confirmed) return;

    setBusy("Delete episode");
    setMessage("Deleting episode");
    setMessageTone("info");
    try {
      await api.deleteEpisode(episode.id);
      setEpisodes((current) => {
        const next = current.filter((item) => item.id !== episode.id);
        if (selectedEpisodeId === episode.id) {
          const nextSelectedEpisodeId = next[0]?.id ?? "";
          setSelectedEpisodeId(nextSelectedEpisodeId);
          setClips([]);
          setSelectedClipId("");
          setEpisodeEvents([]);
        }
        return next;
      });
      removeStoredEpisodeEvents(episode.id);
      setMessage("Episode deleted");
      setMessageTone("success");
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setMessage(error instanceof Error ? error.message : "Unable to delete episode");
      setMessageTone("error");
    } finally {
      setBusy("");
    }
  }

  async function loadClips() {
    if (!selectedEpisodeId) return;
    try {
      const data = await api.clips(selectedEpisodeId, { clip_type: clipTypeFilter, status: statusFilter });
      setClips(data);
      setSelectedClipId((current) => (data.some((clip) => clip.id === current) ? current : data[0]?.id ?? ""));
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setMessage(error instanceof Error ? error.message : "Unable to load clips");
      setMessageTone("error");
    }
  }

  function mergeClip(updatedClip: Clip) {
    setClips((current) =>
      current.map((clip) => (clip.id === updatedClip.id ? updatedClip : clip))
    );
    setSelectedClipId(updatedClip.id);
  }

  function mergeRenderedClips(clip: Clip, renderedClips: RenderedClip[]) {
    setClips((current) =>
      current.map((item) =>
        item.id === clip.id
          ? { ...item, rendered_clips: [...item.rendered_clips, ...renderedClips] }
          : item
      )
    );
    setSelectedClipId(clip.id);
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

  function updateRenderType(renderType: string, enabled: boolean) {
    setRenderTypes((current) => {
      const selected = enabled
        ? Array.from(new Set([...current, renderType]))
        : current.filter((item) => item !== renderType);
      return selected.length ? selected : [renderType];
    });
  }

  function createEpisode(event: FormEvent) {
    event.preventDefault();
    run("Episode", () => api.createEpisode(episodeCreatePayload()), (episode) => {
      setEpisodes((current) => [episode, ...current]);
      setSelectedEpisodeId(episode.id);
      setCreateForm({
        title: "",
        guest_name: "",
        guest_role: "",
        guest_company: "",
        theme: "",
        recording_date: ""
      });
    });
  }

  function episodeCreatePayload() {
    return {
      ...createForm,
      title: createForm.title.trim() || "Untitled episode",
      guest_name: createForm.guest_name.trim() || null,
      guest_role: createForm.guest_role.trim() || null,
      guest_company: createForm.guest_company.trim() || null,
      theme: createForm.theme.trim() || null,
      recording_date: createForm.recording_date.trim() || null
    };
  }

  function createUntitledEpisode() {
    run("Episode", () => api.createEpisode({ title: "Untitled episode" }), (episode) => {
      setEpisodes((current) => [episode, ...current]);
      setSelectedEpisodeId(episode.id);
    });
  }

  async function saveEpisodeDetails(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId) return;
    setEpisodeDetailsBusy(true);
    setEpisodeDetailsMessage("");
    try {
      const updated = await api.updateEpisode(selectedEpisodeId, {
        title: episodeDetailsForm.title.trim() || "Untitled episode",
        guest_name: episodeDetailsForm.guest_name.trim() || null,
        guest_role: episodeDetailsForm.guest_role.trim() || null,
        guest_company: episodeDetailsForm.guest_company.trim() || null,
        theme: episodeDetailsForm.theme.trim() || null,
        recording_date: episodeDetailsForm.recording_date.trim() || null
      });
      mergeEpisode(updated);
      setEpisodeDetailsTone("success");
      setEpisodeDetailsMessage("Episode details saved.");
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setEpisodeDetailsTone("error");
      setEpisodeDetailsMessage(error instanceof Error ? error.message : "Unable to save episode details");
    } finally {
      setEpisodeDetailsBusy(false);
    }
  }

  async function autoTitleEpisode() {
    if (!selectedEpisodeId) return;
    setEpisodeDetailsBusy(true);
    setEpisodeDetailsMessage("");
    try {
      const updated = await api.autoTitleEpisode(selectedEpisodeId, analysis.ai_provider);
      mergeEpisode(updated);
      setEpisodeDetailsForm((current) => ({ ...current, title: updated.title }));
      setEpisodeDetailsTone("success");
      setEpisodeDetailsMessage("Episode title generated.");
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setEpisodeDetailsTone("error");
      setEpisodeDetailsMessage(error instanceof Error ? error.message : "Unable to generate title");
    } finally {
      setEpisodeDetailsBusy(false);
    }
  }

  function saveContext(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId) return;
    run("Context", () => api.saveContext(selectedEpisodeId, contextForm));
  }

  function uploadTranscript(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId || (!transcriptFile && !transcriptText.trim())) return;
    const form = new FormData();
    if (transcriptFile) form.append("file", transcriptFile);
    if (transcriptText.trim()) form.append("content", transcriptText);
    form.append("source_format", transcriptFile ? transcriptFile.name.split(".").pop() ?? "txt" : "txt");
    run("Transcript", () => api.uploadTranscript(selectedEpisodeId, form), async () => {
      setTranscriptFile(null);
      setTranscriptText("");
      await loadEpisodes();
    });
  }

  function uploadAsset(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId || !assetFile) return;
    const form = new FormData();
    form.append("file", assetFile);
    form.append("asset_type", assetType);
    form.append("is_primary", ["video", "audio"].includes(assetType) ? "true" : "false");
    run("Asset", () => api.uploadAsset(selectedEpisodeId, form), async () => {
      setAssetFile(null);
      await loadEpisodes();
    });
  }

  function analyzeEpisode() {
    if (!selectedEpisodeId || !transcriptReady) return;
    const episodeId = selectedEpisodeId;
    const shouldAutoTitle = isDefaultEpisodeTitle(selectedEpisode?.title);
    run("Analysis", () => api.analyze(episodeId, analysis), async (analysisRun) => {
      rememberCompletedAnalysisEvent(episodeId, analysisRun);
      await Promise.all([loadEpisodes(), loadClips()]);
      if (shouldAutoTitle) {
        try {
          const updated = await api.autoTitleEpisode(episodeId, analysis.ai_provider);
          mergeEpisode(updated);
        } catch (error) {
          if (handleAuthFailure(error)) return;
        }
      }
    });
  }

  function rememberCompletedAnalysisEvent(episodeId: string, analysisRun: AnalysisRun) {
    const completedEvent: EpisodeEvent = {
      id: Date.now(),
      episode_id: episodeId,
      event_type: "analysis.completed",
      message: `Analysis completed with ${analysisRun.generated_clip_count} clips`,
      level: "success",
      progress: 100,
      data: {
        analysis_run_id: analysisRun.id,
        generated_clip_count: analysisRun.generated_clip_count,
        source: "api_completion_fallback"
      },
      created_at: new Date().toISOString()
    };

    setEpisodeEvents((current) => {
      const alreadyStored = current.some(
        (event) =>
          event.event_type === "analysis.completed" &&
          event.data.analysis_run_id === analysisRun.id
      );
      if (alreadyStored) return current;
      const next = mergeEpisodeEvent(current, completedEvent);
      storeEpisodeEvents(episodeId, next);
      return next;
    });
  }

  function setClipStatus(clip: Clip, status: string) {
    const userName = reviewerName.trim() || "AURORA Demo";
    run(
      statusActionLabels[status] ?? "Update clip",
      () => api.updateClipStatus(clip.id, status, "", userName),
      async (updatedClip) => {
        mergeClip(updatedClip);
        await loadClips();
      }
    );
  }

  function renderClip(clip: Clip) {
    if (!hasMediaAsset) {
      setMessage("Upload a video or audio asset before rendering clips.");
      setMessageTone("error");
      return;
    }
    run("Render", () => api.renderClip(clip.id, renderTypes), async (renderedClips) => {
      mergeRenderedClips(clip, renderedClips);
      await loadClips();
    });
  }

  function exportEpisode() {
    if (!selectedEpisodeId) return;
    run("Export", () => api.exportEpisode(selectedEpisodeId), (pack) => {
      if (pack.status === "completed") {
        window.open(api.downloadExportUrl(pack.id), "_blank");
      }
    });
  }

  if (!authChecked) {
    return (
      <main className="auth-screen">
        <section className="auth-card loading-card">
          <div className="brand large">
            <div className="brand-mark">
              <img src={aidxLogo} alt="AIDX" />
            </div>
            <div>
              <strong>AURORA PRISM</strong>
              <span>Operations Console</span>
            </div>
          </div>
          <div className="status-line">Checking session</div>
        </section>
      </main>
    );
  }

  if (!authSession) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="brand large">
            <div className="brand-mark">
              <img src={aidxLogo} alt="AIDX" />
            </div>
            <div>
              <strong>AURORA PRISM</strong>
              <span>Operations Console</span>
            </div>
          </div>

          <form className="login-form" onSubmit={authMode === "login" ? login : signup}>
            <div className="login-title">
              <ShieldCheck size={22} />
              <div>
                <h1>{authMode === "login" ? "Sign in" : "Create account"}</h1>
                <p>{authMode === "login" ? "Use your operator credentials." : "Create a workspace user."}</p>
              </div>
            </div>
            {authMode === "signup" && (
              <label>
                Display name
                <input
                  autoComplete="name"
                  value={signupForm.display_name}
                  onChange={(event) => setSignupForm({ ...signupForm, display_name: event.target.value })}
                />
              </label>
            )}
            <label>
              Username
              <input
                autoComplete="username"
                minLength={authMode === "signup" ? 3 : undefined}
                value={authMode === "login" ? loginForm.username : signupForm.username}
                onChange={(event) =>
                  authMode === "login"
                    ? setLoginForm({ ...loginForm, username: event.target.value })
                    : setSignupForm({ ...signupForm, username: event.target.value })
                }
              />
            </label>
            <label>
              Password
              <input
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
                minLength={authMode === "signup" ? MIN_SIGNUP_PASSWORD_LENGTH : undefined}
                type="password"
                value={authMode === "login" ? loginForm.password : signupForm.password}
                onChange={(event) =>
                  authMode === "login"
                    ? setLoginForm({ ...loginForm, password: event.target.value })
                    : setSignupForm({ ...signupForm, password: event.target.value })
                }
              />
            </label>
            {authMode === "signup" && (
              <label>
                Confirm password
                <input
                  autoComplete="new-password"
                  minLength={MIN_SIGNUP_PASSWORD_LENGTH}
                  type="password"
                  value={signupForm.confirmPassword}
                  onChange={(event) => setSignupForm({ ...signupForm, confirmPassword: event.target.value })}
                />
              </label>
            )}
            {loginError && (
              <div className="status-line error" role="alert">
                {loginError}
              </div>
            )}
            <button
              type="submit"
              disabled={
                loggingIn ||
                (authMode === "login"
                  ? !loginForm.username || !loginForm.password
                  : !signupForm.username || !signupForm.password || !signupForm.confirmPassword)
              }
            >
              <LockKeyhole size={16} />
              {loggingIn ? "Working" : authMode === "login" ? "Sign in" : "Create account"}
            </button>
            <button
              className="link-button"
              type="button"
              onClick={() => {
                setAuthMode((current) => {
                  const next = current === "login" ? "signup" : "login";
                  replaceBrowserPath(next === "signup" ? SIGNUP_PATH : LOGIN_PATH);
                  return next;
                });
                setLoginError("");
              }}
            >
              {authMode === "login" ? "Create an account" : "Sign in instead"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <>
    <main className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
        <div className="sidebar-top">
          {!sidebarCollapsed && (
            <div className="brand">
              <div className="brand-mark">
                <img src={aidxLogo} alt="AIDX" />
              </div>
              <div>
                <strong>AURORA PRISM</strong>
                <span>Operations Console</span>
              </div>
            </div>
          )}
          <button
            className="ghost icon-button"
            onClick={() => setSidebarCollapsed((current) => !current)}
            aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
            title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>

        {sidebarCollapsed ? (
          <div className="collapsed-rail">
            <button
              className="sidebar-quick-create"
              onClick={createUntitledEpisode}
              disabled={Boolean(busy)}
              aria-label="New episode"
              title="New episode"
            >
              <Sparkles size={18} />
            </button>
          </div>
        ) : (
          <>
        <div className="profile-panel">
          <div className="profile-avatar">
            <UserRound size={18} />
          </div>
          <div>
            <strong>{authSession.user.display_name}</strong>
            <small>{authSession.user.role}</small>
          </div>
          <button className="ghost icon-button" onClick={openSettings} aria-label="User settings" title="User settings">
            <Settings size={16} />
          </button>
          <button className="ghost icon-button" onClick={logout} aria-label="Log out" title="Log out">
            <LogOut size={16} />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Workspace">
          <a href="#intake">Intake</a>
          <a href="#instructions">Instructions</a>
          <a href="#board">Board</a>
        </nav>

        <section className="sidebar-history" aria-label="Episode history">
          <div className="sidebar-history-title">
            <strong>History</strong>
            <span>{episodes.length}</span>
          </div>
          <div className="episode-list">
            {episodes.map((episode) => (
              <article
                className={`episode-card ${episode.id === selectedEpisodeId ? "active" : ""}`}
                key={episode.id}
              >
                <button
                  className="episode-card-main"
                  onClick={() => setSelectedEpisodeId(episode.id)}
                  type="button"
                >
                  <strong>{episode.title}</strong>
                  <span className={`status-pill status-${episode.status}`}>{episode.status}</span>
                  <small>
                    {episode.clip_count} clips · {episode.asset_count} assets · {episode.transcript_segment_count} segments
                  </small>
                </button>
                <button
                  className="episode-delete-button"
                  disabled={Boolean(busy)}
                  onClick={() => deleteEpisode(episode)}
                  type="button"
                  aria-label={`Delete ${episode.title}`}
                  title="Delete history"
                >
                  <Trash2 size={15} />
                </button>
              </article>
            ))}
            {!episodes.length && <div className="sidebar-empty">No episode history</div>}
          </div>
        </section>

        <form className="sidebar-create" onSubmit={createEpisode}>
          <div className="sidebar-create-title">
            <FileText size={15} />
            <span>New episode</span>
          </div>
          <div className="sidebar-create-row">
            <input
              value={createForm.title}
              onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })}
              placeholder="Episode title"
            />
            <button type="submit" disabled={Boolean(busy)} aria-label="Create episode" title="Create episode">
              <Sparkles size={16} />
            </button>
          </div>
        </form>
          </>
        )}
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">
              <Radio size={14} />
              Review Operations
            </span>
            <h1>{selectedEpisode?.title ?? "New episode workspace"}</h1>
            <p>{selectedEpisode?.guest_name ?? "Create or select an episode"}</p>
          </div>
          <div className="topbar-actions">
            <button
              className="ghost icon-button"
              onClick={openEpisodeDetails}
              disabled={!selectedEpisodeId}
              aria-label="Episode details"
              title="Episode details"
            >
              <FileText size={16} />
            </button>
            <button className="ghost icon-button" onClick={() => loadEpisodes()} aria-label="Refresh episodes" title="Refresh episodes">
              <RefreshCw size={16} />
            </button>
            <button onClick={analyzeEpisode} disabled={!canAnalyze}>
              <WandSparkles size={16} />
              Analyze with {analysis.mode === "mock" ? "rules" : "LLM"}
            </button>
            <button className="secondary" onClick={exportEpisode} disabled={!selectedEpisodeId || Boolean(busy)}>
              <Download size={16} />
              Export
            </button>
          </div>
        </header>

        {currentEvent && (
          <div className={`operation-progress-line ${currentEvent.level}`} aria-live="polite">
            <span className="operation-progress-label">
              {currentEventProgress ?? 0}%
            </span>
            <div className="operation-progress-track" aria-label={`Progress ${currentEventProgress ?? 0}%`}>
              <span style={{ width: `${currentEventProgress ?? 0}%` }} />
            </div>
            <span className="operation-progress-text">
              {currentEvent.message}
            </span>
          </div>
        )}

        <section className="metrics-strip">
          <div>
            <span>{clips.length}</span>
            <small>Total clips</small>
          </div>
          <div>
            <span>{recommendedCount}</span>
            <small>Recommended</small>
          </div>
          <div>
            <span>{approvedCount}</span>
            <small>Approved</small>
          </div>
          <div>
            <span>{selectedEpisode?.transcript_segment_count ?? 0}</span>
            <small>Segments</small>
          </div>
        </section>

        {message && <div className={`status-line ${messageTone}`}>{message}</div>}

        <div className="grid-layout">
          <section className="panel intake" id="intake">
            <div className="panel-title">
              <Upload size={18} />
              <h2>Intake</h2>
              <span>{transcriptReady ? "Ready" : "Needs transcript"}</span>
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

            <form className="stack upload-block" onSubmit={uploadAsset}>
              <div className="section-kicker">
                <Layers3 size={15} />
                Assets
              </div>
              <div className="upload-row">
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
              </div>
            </form>

            <form className="stack" onSubmit={uploadTranscript}>
              <div className="section-kicker">
                <FileText size={15} />
                Transcript
              </div>
              <label>
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
              <button type="submit" disabled={!canUploadTranscript}>
                <Upload size={16} />
                Save Transcript
              </button>
            </form>
          </section>

          <section className="panel controls" id="instructions">
            <div className="panel-title">
              <Scissors size={18} />
              <h2>Clip Instructions</h2>
              <span>{modeLabels[analysis.mode]}</span>
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
            <label>
              Analysis mode
              <select
                value={analysis.mode}
                onChange={(event) =>
                  setAnalysis({ ...analysis, mode: event.target.value as "mock" | "hybrid" | "openai" })
                }
              >
                <option value="hybrid">Hybrid LLM</option>
                <option value="openai">LLM only</option>
                <option value="mock">Mock heuristic</option>
              </select>
            </label>
            <div className="mode-summary">
              <Bot size={18} />
              <span>
                {analysis.mode === "mock"
                  ? "Uses local scoring and template metadata without provider calls."
                  : analysis.mode === "hybrid"
                    ? "LLM ranks shortlisted moments and falls back to local scoring if needed."
                    : "Requires a live provider response before clips are saved."}
              </span>
            </div>
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
            <button onClick={analyzeEpisode} disabled={!canAnalyze}>
              <WandSparkles size={16} />
              Run Analysis
            </button>
          </section>

          <section className="panel board" id="board">
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
                    <strong>{clip.clip_type} · {clip.moment_type.replace("_", " ")}</strong>
                    <small>
                      {formatTime(clip.start_seconds)}-{formatTime(clip.end_seconds)} ·{" "}
                      {Math.round(clip.duration_seconds)}s · {clip.status}
                    </small>
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
                    <span className="eyebrow">
                      <Clock3 size={14} />
                      {selectedClip.status}
                    </span>
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
                          {key.replace(/_/g, " ")}
                          <strong>{value}</strong>
                        </span>
                      ))}
                </div>

                <div className="metadata-tabs">
                  {selectedClip.metadata.map((item) => (
                    <article key={item.platform} className="metadata-card">
                      <strong>{item.platform.replace(/_/g, " ")}</strong>
                      <h3>{item.title}</h3>
                      <p>{item.hook}</p>
                      <p>{item.caption}</p>
                      <div className="metadata-actions">
                        <small>{item.soft_cta}</small>
                        <small>{item.business_cta}</small>
                      </div>
                      <small>{item.hashtags.join(" ")}</small>
                    </article>
                  ))}
                </div>

                <div className="render-options">
                  <div className="section-kicker">
                    <Activity size={15} />
                    Render outputs
                  </div>
                  {!hasMediaAsset && (
                    <p className="render-hint">Upload a video or audio asset before rendering clips.</p>
                  )}
                  <div className="toggle-grid">
                    {renderOptions.map(([key, label]) => (
                      <label key={key}>
                        <input
                          type="checkbox"
                          checked={renderTypes.includes(key)}
                          onChange={(event) => updateRenderType(key, event.target.checked)}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                </div>

                <div className="actions">
                  <button onClick={() => setClipStatus(selectedClip, "approved")} disabled={Boolean(busy)}>
                    <CheckCircle2 size={16} />
                    Approve
                  </button>
                  <button className="secondary" onClick={() => setClipStatus(selectedClip, "needs_revision")} disabled={Boolean(busy)}>
                    <RefreshCw size={16} />
                    Revision
                  </button>
                  <button className="danger" onClick={() => setClipStatus(selectedClip, "rejected")} disabled={Boolean(busy)}>
                    <XCircle size={16} />
                    Reject
                  </button>
                  <button
                    className="secondary"
                    onClick={() => renderClip(selectedClip)}
                    disabled={Boolean(busy) || !hasMediaAsset}
                  >
                    <Play size={16} />
                    Render
                  </button>
                </div>

                <div className="render-list">
                  {selectedClip.rendered_clips.map((rendered) =>
                    rendered.status === "completed" ? (
                      <a key={rendered.id} href={api.downloadRenderUrl(rendered.id)} target="_blank" rel="noreferrer">
                        {rendered.render_type} · {rendered.status}
                      </a>
                    ) : (
                      <div key={rendered.id} className={`render-item ${rendered.status}`}>
                        <span>{rendered.render_type} · {rendered.status}</span>
                        {rendered.error && <small>{rendered.error}</small>}
                      </div>
                    )
                  )}
                </div>
              </>
            ) : (
              <div className="empty">Select a clip</div>
            )}
          </section>
        </div>
      </section>
    </main>
    {episodeDetailsOpen && selectedEpisode && (
      <div className="modal-backdrop" role="presentation">
        <section className="settings-dialog episode-dialog" role="dialog" aria-modal="true" aria-labelledby="episode-details-title">
          <div className="settings-head">
            <div>
              <span className="eyebrow">
                <FileText size={14} />
                Episode Workspace
              </span>
              <h2 id="episode-details-title">Episode details</h2>
            </div>
            <button
              className="ghost icon-button"
              type="button"
              onClick={() => setEpisodeDetailsOpen(false)}
              aria-label="Close episode details"
            >
              <XCircle size={18} />
            </button>
          </div>

          <form className="settings-form" onSubmit={saveEpisodeDetails}>
            <div className="settings-section">
              <div className="section-kicker">
                <FileText size={15} />
                Title
              </div>
              <label>
                Episode title
                <input
                  maxLength={255}
                  value={episodeDetailsForm.title}
                  onChange={(event) => setEpisodeDetailsForm({ ...episodeDetailsForm, title: event.target.value })}
                  placeholder="Untitled episode"
                />
              </label>
              <button
                className="secondary"
                type="button"
                onClick={autoTitleEpisode}
                disabled={episodeDetailsBusy || !selectedEpisodeId}
              >
                <Sparkles size={16} />
                {episodeDetailsBusy ? "Working" : "Auto title"}
              </button>
            </div>

            <div className="settings-section">
              <div className="section-kicker">
                <UserRound size={15} />
                Guest context
              </div>
              <div className="two-col">
                <label>
                  Guest name
                  <input
                    value={episodeDetailsForm.guest_name}
                    onChange={(event) => setEpisodeDetailsForm({ ...episodeDetailsForm, guest_name: event.target.value })}
                  />
                </label>
                <label>
                  Company
                  <input
                    value={episodeDetailsForm.guest_company}
                    onChange={(event) => setEpisodeDetailsForm({ ...episodeDetailsForm, guest_company: event.target.value })}
                  />
                </label>
              </div>
              <div className="two-col">
                <label>
                  Role
                  <input
                    value={episodeDetailsForm.guest_role}
                    onChange={(event) => setEpisodeDetailsForm({ ...episodeDetailsForm, guest_role: event.target.value })}
                  />
                </label>
                <label>
                  Recording date
                  <input
                    value={episodeDetailsForm.recording_date}
                    onChange={(event) => setEpisodeDetailsForm({ ...episodeDetailsForm, recording_date: event.target.value })}
                    placeholder="YYYY-MM-DD"
                  />
                </label>
              </div>
              <label>
                Theme
                <input
                  value={episodeDetailsForm.theme}
                  onChange={(event) => setEpisodeDetailsForm({ ...episodeDetailsForm, theme: event.target.value })}
                />
              </label>
            </div>

            {episodeDetailsMessage && (
              <div className={`status-line ${episodeDetailsTone}`} role="alert">
                {episodeDetailsMessage}
              </div>
            )}

            <div className="settings-actions">
              <button className="ghost" type="button" onClick={() => setEpisodeDetailsOpen(false)}>
                Cancel
              </button>
              <button type="submit" disabled={episodeDetailsBusy}>
                <Save size={16} />
                {episodeDetailsBusy ? "Saving" : "Save details"}
              </button>
            </div>
          </form>
        </section>
      </div>
    )}
    {settingsOpen && (
      <div className="modal-backdrop" role="presentation">
        <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
          <div className="settings-head">
            <div>
              <span className="eyebrow">
                <Settings size={14} />
                User Settings
              </span>
              <h2 id="settings-title">Account</h2>
            </div>
            <button className="ghost icon-button" type="button" onClick={() => setSettingsOpen(false)} aria-label="Close settings">
              <XCircle size={18} />
            </button>
          </div>

          <form className="settings-form" onSubmit={saveSettings}>
            <div className="settings-section">
              <div className="section-kicker">
                <UserRound size={15} />
                Profile
              </div>
              <div className="two-col">
                <label>
                  Display name
                  <input
                    value={settingsForm.display_name}
                    onChange={(event) => setSettingsForm({ ...settingsForm, display_name: event.target.value })}
                  />
                </label>
                <label>
                  Username
                  <input
                    minLength={3}
                    value={settingsForm.username}
                    onChange={(event) => setSettingsForm({ ...settingsForm, username: event.target.value })}
                  />
                </label>
              </div>
            </div>

            <div className="settings-section">
              <div className="section-kicker">
                <KeyRound size={15} />
                Password
              </div>
              <label>
                Current password
                <input
                  autoComplete="current-password"
                  type="password"
                  value={settingsForm.currentPassword}
                  onChange={(event) => setSettingsForm({ ...settingsForm, currentPassword: event.target.value })}
                />
              </label>
              <div className="two-col">
                <label>
                  New password
                  <input
                    autoComplete="new-password"
                    minLength={MIN_SIGNUP_PASSWORD_LENGTH}
                    type="password"
                    value={settingsForm.newPassword}
                    onChange={(event) => setSettingsForm({ ...settingsForm, newPassword: event.target.value })}
                  />
                </label>
                <label>
                  Confirm new password
                  <input
                    autoComplete="new-password"
                    minLength={MIN_SIGNUP_PASSWORD_LENGTH}
                    type="password"
                    value={settingsForm.confirmPassword}
                    onChange={(event) => setSettingsForm({ ...settingsForm, confirmPassword: event.target.value })}
                  />
                </label>
              </div>
            </div>

            {settingsMessage && (
              <div className={`status-line ${settingsTone}`} role="alert">
                {settingsMessage}
              </div>
            )}

            <div className="settings-actions">
              <button className="ghost" type="button" onClick={() => setSettingsOpen(false)}>
                Cancel
              </button>
              <button type="submit" disabled={settingsBusy || !settingsForm.username.trim()}>
                <Save size={16} />
                {settingsBusy ? "Saving" : "Save settings"}
              </button>
            </div>
          </form>
        </section>
      </div>
    )}
    </>
  );
}

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  return `${minutes}:${sec.toString().padStart(2, "0")}`;
}

function clampProgress(progress: number) {
  return Math.min(100, Math.max(0, Math.round(progress)));
}

function eventProgress(event: EpisodeEvent) {
  return typeof event.progress === "number" ? clampProgress(event.progress) : null;
}

function isCompletedEpisodeEvent(event: EpisodeEvent) {
  if (event.level === "error") return false;
  return eventProgress(event) === 100 || event.event_type.endsWith(".completed");
}

function isDefaultEpisodeTitle(title?: string | null) {
  return !title || title.trim().toLowerCase() === "untitled episode";
}

function mergeEpisodeEvent(events: EpisodeEvent[], event: EpisodeEvent) {
  const visibleEvents = events.filter((item) => !isCompletedEpisodeEvent(item));
  const withoutDuplicate = visibleEvents.filter((item) => item.id !== event.id && !sameEpisodeEvent(item, event));
  if (isCompletedEpisodeEvent(event)) {
    return pruneCompletedOperationEvents(withoutDuplicate, event);
  }
  return [event, ...withoutDuplicate].slice(0, EVENT_HISTORY_LIMIT);
}

function pruneCompletedOperationEvents(events: EpisodeEvent[], completedEvent: EpisodeEvent) {
  const group = eventOperationGroup(completedEvent);
  return events.filter((event) => eventOperationGroup(event) !== group).slice(0, EVENT_HISTORY_LIMIT);
}

function eventOperationGroup(event: EpisodeEvent) {
  const rawGroup = event.event_type.split(".")[0] || "system";
  return rawGroup === "llm" ? "analysis" : rawGroup;
}

function sameEpisodeEvent(left: EpisodeEvent, right: EpisodeEvent) {
  if (left.event_type !== right.event_type) return false;
  if (
    typeof left.data.analysis_run_id === "string" &&
    left.data.analysis_run_id === right.data.analysis_run_id
  ) {
    return true;
  }
  return false;
}

function eventStorageKey(episodeId: string) {
  return `aurora-prism:episode-events:${episodeId}`;
}

function readStoredEpisodeEvents(episodeId: string) {
  try {
    const stored = window.localStorage.getItem(eventStorageKey(episodeId));
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed)
      ? (parsed as EpisodeEvent[])
          .filter((event) => !isCompletedEpisodeEvent(event))
          .slice(0, EVENT_HISTORY_LIMIT)
      : [];
  } catch {
    return [];
  }
}

function storeEpisodeEvents(episodeId: string, events: EpisodeEvent[]) {
  try {
    const visibleEvents = events.filter((event) => !isCompletedEpisodeEvent(event));
    window.localStorage.setItem(
      eventStorageKey(episodeId),
      JSON.stringify(visibleEvents.slice(0, EVENT_HISTORY_LIMIT))
    );
  } catch {
    // Browser storage may be unavailable in private or restricted sessions.
  }
}

function removeStoredEpisodeEvents(episodeId: string) {
  try {
    window.localStorage.removeItem(eventStorageKey(episodeId));
  } catch {
    // Browser storage may be unavailable in private or restricted sessions.
  }
}

function readStoredAuthSession() {
  try {
    const stored = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as AuthSession;
    return parsed?.access_token && parsed?.user ? parsed : null;
  } catch {
    return null;
  }
}

function storeAuthSession(session: AuthSession) {
  try {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Browser storage may be unavailable in private or restricted sessions.
  }
}

function clearStoredAuthSession() {
  try {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch {
    // Browser storage may be unavailable in private or restricted sessions.
  }
}

function initialAuthMode(): "login" | "signup" {
  return window.location.pathname === SIGNUP_PATH ? "signup" : "login";
}

function isAuthPath() {
  return window.location.pathname === LOGIN_PATH || window.location.pathname === SIGNUP_PATH;
}

function replaceBrowserPath(path: string) {
  if (window.location.pathname === path) return;
  window.history.replaceState(null, "", path);
}
