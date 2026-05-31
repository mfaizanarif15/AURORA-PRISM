import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
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
import type {
  AnalysisEvent,
  AnalysisPayload,
  AnalysisSectionKey,
  AuthSession,
  Clip,
  Episode,
  RenderedClip
} from "./types";

const AUTH_STORAGE_KEY = "aurora-prism:auth-session";
const MIN_SIGNUP_PASSWORD_LENGTH = 8;
const APP_PATH = "/app";
const LOGIN_PATH = "/auth/login";
const SIGNUP_PATH = "/auth/signup";

const outputSections: Array<{
  key: AnalysisSectionKey;
  label: string;
  targetPlatform: string;
  defaultMinSeconds: number;
  defaultMaxSeconds: number;
}> = [
  { key: "tiktok", label: "TikTok", targetPlatform: "tiktok", defaultMinSeconds: 30, defaultMaxSeconds: 60 },
  {
    key: "instagram_reels",
    label: "Reels",
    targetPlatform: "instagram_reels",
    defaultMinSeconds: 30,
    defaultMaxSeconds: 75
  },
  {
    key: "youtube_shorts",
    label: "YouTube Shorts",
    targetPlatform: "youtube_shorts",
    defaultMinSeconds: 30,
    defaultMaxSeconds: 90
  },
  { key: "linkedin", label: "LinkedIn", targetPlatform: "linkedin", defaultMinSeconds: 45, defaultMaxSeconds: 120 },
  { key: "highlights", label: "Highlights", targetPlatform: "generic", defaultMinSeconds: 180, defaultMaxSeconds: 360 }
];

const renderOptions = [
  ["video", "Video"],
  ["audio", "Audio"]
];

const DEFAULT_AI_PROVIDER: AnalysisPayload["ai_provider"] = "azure_openai";
const DEFAULT_ANALYSIS_MODE: AnalysisPayload["mode"] = "hybrid";
const DOCUMENT_ACCEPT = ".pdf,.docx,.txt,.md,.csv,.vtt,.srt";
const TRANSCRIPT_ACCEPT = ".txt,.md,.vtt,.srt,.csv,.pdf,.docx,.mp3,.mp4,.mpeg,.mpga,.m4a,.wav,.webm,audio/*,video/mp4,video/webm";
const DEFAULT_SECTION_COUNT = 3;

const statusActionLabels: Record<string, string> = {
  approved: "Approve output",
  rejected: "Reject output"
};

function renderTypeLabel(renderType: string) {
  return renderType === "audio" ? "Audio" : "Video";
}

function showRenderedClip(rendered: RenderedClip) {
  if (rendered.status !== "failed") return true;
  const error = rendered.error?.toLowerCase() ?? "";
  return !(error.includes("no such file or directory") && error.includes("ffmpeg"));
}

const emptyContext = {
  icp: "",
  target_audience: "",
  audience_pain_points: "",
  hot_topic: "",
  business_objectives: "",
  episode_plan: "",
  preferred_platforms: ["youtube_shorts", "tiktok", "instagram_reels", "linkedin"],
  editor_notes: ""
};

function defaultAnalysisSections(): AnalysisPayload["sections"] {
  return {
    tiktok: defaultAnalysisSection("tiktok", false),
    instagram_reels: defaultAnalysisSection("instagram_reels", false),
    youtube_shorts: defaultAnalysisSection("youtube_shorts", false),
    linkedin: defaultAnalysisSection("linkedin", false),
    highlights: defaultAnalysisSection("highlights", false)
  };
}

function defaultAnalysisSection(sectionKey: AnalysisSectionKey, enabled: boolean) {
  const section = outputSections.find((item) => item.key === sectionKey)!;
  return {
    enabled,
    target_count: DEFAULT_SECTION_COUNT,
    duration_min_seconds: section.defaultMinSeconds,
    duration_max_seconds: section.defaultMaxSeconds
  };
}

function formatDurationRange(minSeconds: number | null, maxSeconds: number | null) {
  if (minSeconds === null || maxSeconds === null) {
    return "Default";
  }
  if (minSeconds >= 60 && minSeconds % 60 === 0 && maxSeconds % 60 === 0) {
    return `${minSeconds / 60}-${maxSeconds / 60}m`;
  }
  return `${minSeconds}-${maxSeconds}s`;
}

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
    recording_date: ""
  });
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedEpisodeId, setSelectedEpisodeId] = useState("");
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClipId, setSelectedClipId] = useState("");
  const [busy, setBusy] = useState("");
  const [analysisEvent, setAnalysisEvent] = useState<AnalysisEvent | null>(null);
  const analysisEventSourceRef = useRef<EventSource | null>(null);
  const analysisEventStartedAtRef = useRef("");
  const [reviewerName, setReviewerName] = useState("AURORA Demo");
  const [createForm, setCreateForm] = useState({
    title: "",
    guest_name: "",
    guest_role: "",
    guest_company: "",
    recording_date: ""
  });
  const [contextForm, setContextForm] = useState(emptyContext);
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptFile, setTranscriptFile] = useState<File | null>(null);
  const [audioAssetFile, setAudioAssetFile] = useState<File | null>(null);
  const [videoAssetFile, setVideoAssetFile] = useState<File | null>(null);
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [renderTypes, setRenderTypes] = useState<string[]>([]);
  const [renderError, setRenderError] = useState("");
  const [purposeFilter, setPurposeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisPayload>({
    ai_provider: DEFAULT_AI_PROVIDER,
    duration_min_seconds: null,
    duration_max_seconds: null,
    custom_instructions: "",
    mode: DEFAULT_ANALYSIS_MODE,
    sections: defaultAnalysisSections()
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
  }, [authSession?.access_token, selectedEpisodeId, purposeFilter, statusFilter]);

  useEffect(() => {
    return () => closeAnalysisEventStream();
  }, []);

  useEffect(() => {
    closeAnalysisEventStream();
    setAnalysisEvent(null);
  }, [selectedEpisodeId]);

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
      recording_date: selectedEpisode.recording_date ?? ""
    });
    setEpisodeDetailsMessage("");
  }, [selectedEpisode?.id]);
  const selectedClip = useMemo(
    () => clips.find((clip) => clip.id === selectedClipId) ?? clips[0],
    [clips, selectedClipId]
  );
  useEffect(() => {
    setRenderError("");
  }, [selectedClip?.id]);
  const approvedCount = clips.filter((clip) => clip.status === "approved").length;
  const groupedOutputs = outputSections
    .map((section) => ({
      ...section,
      items: clips.filter((clip) => clip.target_platform === section.targetPlatform)
    }))
    .filter((section) => section.items.length > 0);
  const transcriptReady = Boolean(selectedEpisode?.transcript_segment_count);
  const hasMediaAsset = Boolean(selectedEpisode?.media_asset_count);
  const hasSelectedOutputSection = Object.values(analysis.sections).some((section) => section.enabled);
  const canAnalyze = Boolean(selectedEpisodeId && transcriptReady && hasSelectedOutputSection && !busy);
  const canUploadTranscript = Boolean(selectedEpisodeId && !busy && (transcriptFile || transcriptText.trim()));
  const visibleAnalysisEvent = analysisEvent?.episode_id === selectedEpisodeId ? analysisEvent : null;

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
    closeAnalysisEventStream();
    setAnalysisEvent(null);
    setBusy("");
  }

  async function run<T>(
    label: string,
    action: () => Promise<T>,
    done?: (result: T) => void | Promise<void>
  ) {
    setBusy(label);
    try {
      const result = await action();
      await done?.(result);
    } catch (error) {
      if (handleAuthFailure(error)) return;
      console.error(error instanceof Error ? error.message : "Something went wrong");
    } finally {
      setBusy("");
    }
  }

  function closeAnalysisEventStream() {
    analysisEventSourceRef.current?.close();
    analysisEventSourceRef.current = null;
  }

  function startAnalysisEventStream(episodeId: string) {
    const startedAt = new Date().toISOString();
    analysisEventStartedAtRef.current = startedAt;
    closeAnalysisEventStream();
    setAnalysisEvent({
      id: Date.now(),
      episode_id: episodeId,
      event_type: "analysis.connecting",
      message: "Starting analysis",
      level: "info",
      progress: 0,
      data: {},
      created_at: startedAt
    });

    const source = new EventSource(api.analysisEventsUrl(episodeId, startedAt));
    analysisEventSourceRef.current = source;
    source.addEventListener("analysis", (event) => {
      try {
        const parsed = JSON.parse(event.data) as AnalysisEvent;
        if (
          parsed.episode_id !== episodeId ||
          isBeforeIsoTime(parsed.created_at, analysisEventStartedAtRef.current)
        ) {
          return;
        }
        setAnalysisEvent(parsed);
        if (isTerminalAnalysisEvent(parsed)) {
          source.close();
          if (analysisEventSourceRef.current === source) {
            analysisEventSourceRef.current = null;
          }
        }
      } catch {
        // Ignore malformed stream payloads without interrupting analysis.
      }
    });
    source.onerror = () => {
      if (analysisEventSourceRef.current !== source) return;
      source.close();
      analysisEventSourceRef.current = null;
      setAnalysisEvent((current) => {
        if (!current || isTerminalAnalysisEvent(current)) return current;
        return {
          ...current,
          event_type: "analysis.stream_error",
          message: "Analysis progress stream disconnected",
          level: "error"
        };
      });
    };
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
      console.error(error instanceof Error ? error.message : "Unable to load episodes");
    }
  }

  function mergeEpisode(updatedEpisode: Episode) {
    setEpisodes((current) =>
      current.map((episode) => (episode.id === updatedEpisode.id ? updatedEpisode : episode))
    );
  }

  async function deleteEpisode(episode: Episode) {
    const confirmed = window.confirm(
      `Delete "${episode.title}" from history? This removes its outputs, transcripts, assets, and exports.`
    );
    if (!confirmed) return;

    setBusy("Delete episode");
    try {
      await api.deleteEpisode(episode.id);
      setEpisodes((current) => {
        const next = current.filter((item) => item.id !== episode.id);
        if (selectedEpisodeId === episode.id) {
          const nextSelectedEpisodeId = next[0]?.id ?? "";
          setSelectedEpisodeId(nextSelectedEpisodeId);
          setClips([]);
          setSelectedClipId("");
        }
        return next;
      });
    } catch (error) {
      if (handleAuthFailure(error)) return;
      console.error(error instanceof Error ? error.message : "Unable to delete episode");
    } finally {
      setBusy("");
    }
  }

  async function loadClips() {
    if (!selectedEpisodeId) return;
    try {
      const data = await api.clips(selectedEpisodeId, { target_platform: purposeFilter, status: statusFilter });
      setClips(data);
      setSelectedClipId((current) => (data.some((clip) => clip.id === current) ? current : data[0]?.id ?? ""));
    } catch (error) {
      if (handleAuthFailure(error)) return;
      console.error(error instanceof Error ? error.message : "Unable to load outputs");
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

  function updateSectionEnabled(section: AnalysisSectionKey, enabled: boolean) {
    setAnalysis((current) => {
      const nextSections = {
        ...current.sections,
        [section]: { ...current.sections[section], enabled }
      };
      return { ...current, sections: nextSections };
    });
  }

  function updateSectionCount(section: AnalysisSectionKey, value: number) {
    setAnalysis((current) => {
      const targetCount = Math.min(10, Math.max(1, Number.isFinite(value) ? value : DEFAULT_SECTION_COUNT));
      return {
        ...current,
        sections: {
          ...current.sections,
          [section]: { ...current.sections[section], target_count: targetCount }
        }
      };
    });
  }

  function updateSectionDuration(
    section: AnalysisSectionKey,
    field: "duration_min_seconds" | "duration_max_seconds",
    value: number | null
  ) {
    setAnalysis((current) => {
      const nextValue = value === null || !Number.isFinite(value) ? null : Math.min(1800, Math.max(1, value));
      const nextSection = { ...current.sections[section], [field]: nextValue };
      if (
        nextSection.duration_min_seconds !== null &&
        nextSection.duration_max_seconds !== null &&
        nextSection.duration_min_seconds > nextSection.duration_max_seconds
      ) {
        if (field === "duration_min_seconds") {
          nextSection.duration_max_seconds = nextSection.duration_min_seconds;
        } else {
          nextSection.duration_min_seconds = nextSection.duration_max_seconds;
        }
      }
      return {
        ...current,
        sections: {
          ...current.sections,
          [section]: nextSection
        }
      };
    });
  }

  function updateRenderType(renderType: string, enabled: boolean) {
    setRenderTypes((current) => {
      return enabled
        ? Array.from(new Set([...current, renderType]))
        : current.filter((item) => item !== renderType);
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
      const updated = await api.autoTitleEpisode(selectedEpisodeId, DEFAULT_AI_PROVIDER);
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

  function uploadDocument(event: FormEvent) {
    event.preventDefault();
    if (!selectedEpisodeId || !documentFile) return;
    const form = new FormData();
    form.append("file", documentFile);
    form.append("asset_type", "guest_document");
    form.append("is_primary", "false");
    run("Document", () => api.uploadAsset(selectedEpisodeId, form), async () => {
      setDocumentFile(null);
      await loadEpisodes();
    });
  }

  function uploadAsset(event: FormEvent, assetType: "audio" | "video") {
    event.preventDefault();
    const file = assetType === "audio" ? audioAssetFile : videoAssetFile;
    if (!selectedEpisodeId || !file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("asset_type", assetType);
    form.append("is_primary", "true");
    run(assetType === "audio" ? "Audio" : "Video", () => api.uploadAsset(selectedEpisodeId, form), async () => {
      if (assetType === "audio") {
        setAudioAssetFile(null);
      } else {
        setVideoAssetFile(null);
      }
      await loadEpisodes();
    });
  }

  async function analyzeEpisode() {
    if (!selectedEpisodeId || !transcriptReady || !hasSelectedOutputSection) return;
    const episodeId = selectedEpisodeId;
    startAnalysisEventStream(episodeId);
    setBusy("Analysis");
    try {
      await api.analyze(episodeId, analysisPayload());
      await Promise.all([loadEpisodes(), loadClips()]);
    } catch (error) {
      if (handleAuthFailure(error)) return;
      closeAnalysisEventStream();
      setAnalysisEvent({
        id: Date.now(),
        episode_id: episodeId,
        event_type: "analysis.failed",
        message: error instanceof Error ? error.message : "Analysis failed",
        level: "error",
        progress: 100,
        data: {},
        created_at: new Date().toISOString()
      });
    } finally {
      setBusy("");
    }
  }

  function analysisPayload(): AnalysisPayload {
    return {
      ...analysis,
      ai_provider: DEFAULT_AI_PROVIDER,
      mode: DEFAULT_ANALYSIS_MODE
    };
  }

  function setClipStatus(clip: Clip, status: string) {
    const userName = reviewerName.trim() || "AURORA Demo";
    run(
      statusActionLabels[status] ?? "Update output",
      () => api.updateClipStatus(clip.id, status, "", userName),
      async (updatedClip) => {
        mergeClip(updatedClip);
        await loadClips();
      }
    );
  }

  async function deleteOutput(clip: Clip) {
    const confirmed = window.confirm(`Delete output ${clip.purpose} ${clip.rank}?`);
    if (!confirmed) return;

    setBusy("Delete output");
    try {
      await api.deleteClip(clip.id);
      setClips((current) => current.filter((item) => item.id !== clip.id));
      if (selectedClipId === clip.id) {
        setSelectedClipId("");
      }
      await Promise.all([loadClips(), loadEpisodes()]);
    } catch (error) {
      if (handleAuthFailure(error)) return;
      console.error(error instanceof Error ? error.message : "Unable to delete output");
    } finally {
      setBusy("");
    }
  }

  async function renderClip(clip: Clip) {
    if (!hasMediaAsset || renderTypes.length === 0) {
      return;
    }
    setRenderError("");
    setBusy("Render");
    try {
      const renderedClips = await api.renderClip(clip.id, renderTypes);
      mergeRenderedClips(clip, renderedClips);
      await loadClips();
    } catch (error) {
      if (handleAuthFailure(error)) return;
      setRenderError(error instanceof Error ? error.message : "Unable to render output");
    } finally {
      setBusy("");
    }
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
            <small>@{authSession.user.username}</small>
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
            <button className="secondary" onClick={exportEpisode} disabled={!selectedEpisodeId || Boolean(busy)}>
              <Download size={16} />
              Export
            </button>
          </div>
        </header>

        <section className="metrics-strip">
          <div>
            <span>{clips.length}</span>
            <small>Total outputs</small>
          </div>
          <div>
            <span>{approvedCount}</span>
            <small>Approved</small>
          </div>
        </section>

        <div className="grid-layout">
          <section className="panel intake" id="intake">
            <div className="panel-title">
              <Upload size={18} />
              <h2>Intake</h2>
            </div>

            <form className="stack" onSubmit={saveContext}>
              <label>
                Ideal Customer Profile
                <textarea
                  value={contextForm.icp}
                  onChange={(event) => setContextForm({ ...contextForm, icp: event.target.value })}
                  placeholder="Describe the ideal audience for these outputs"
                />
              </label>
              <label>
                Hot topic
                <input
                  value={contextForm.hot_topic}
                  onChange={(event) => setContextForm({ ...contextForm, hot_topic: event.target.value })}
                  placeholder="Main topic or angle for this episode"
                />
              </label>
              <label>
                Episode plan
                <textarea
                  value={contextForm.episode_plan}
                  onChange={(event) => setContextForm({ ...contextForm, episode_plan: event.target.value })}
                  placeholder="Optional notes for what to find or avoid"
                />
              </label>
              <button type="submit" disabled={!selectedEpisodeId || Boolean(busy)}>
                <CheckCircle2 size={16} />
                Save Context
              </button>
            </form>

            <div className="stack upload-block">
              <div className="section-kicker">
                <Layers3 size={15} />
                Assets
              </div>
              <div className="asset-upload-grid">
                <form className="asset-upload-row" onSubmit={(event) => uploadAsset(event, "audio")}>
                  <div className="asset-upload-head">
                    <Mic2 size={16} />
                    <strong>Audio</strong>
                  </div>
                  <input
                    type="file"
                    accept="audio/*"
                    onChange={(event) => setAudioAssetFile(event.currentTarget.files?.[0] ?? null)}
                  />
                  <button type="submit" disabled={!audioAssetFile || !selectedEpisodeId || Boolean(busy)}>
                    <Mic2 size={16} />
                    Upload Audio
                  </button>
                </form>
                <form className="asset-upload-row" onSubmit={(event) => uploadAsset(event, "video")}>
                  <div className="asset-upload-head">
                    <FileVideo size={16} />
                    <strong>Video</strong>
                  </div>
                  <input
                    type="file"
                    accept="video/*"
                    onChange={(event) => setVideoAssetFile(event.currentTarget.files?.[0] ?? null)}
                  />
                  <button type="submit" disabled={!videoAssetFile || !selectedEpisodeId || Boolean(busy)}>
                    <FileVideo size={16} />
                    Upload Video
                  </button>
                </form>
              </div>
            </div>

            <form className="stack upload-block" onSubmit={uploadDocument}>
              <div className="section-kicker">
                <FileText size={15} />
                Documents
              </div>
              <div className="upload-row">
                <input
                  type="file"
                  accept={DOCUMENT_ACCEPT}
                  onChange={(event) => setDocumentFile(event.currentTarget.files?.[0] ?? null)}
                />
                <button type="submit" disabled={!documentFile || !selectedEpisodeId || Boolean(busy)}>
                  <FileText size={16} />
                  Upload Document
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
                accept={TRANSCRIPT_ACCEPT}
                onChange={(event) => setTranscriptFile(event.currentTarget.files?.[0] ?? null)}
              />
              <button type="submit" disabled={!canUploadTranscript}>
                <Upload size={16} />
                Parse Transcript
              </button>
            </form>
          </section>

          <section className="panel controls" id="instructions">
            <div className="panel-title">
              <Scissors size={18} />
              <h2>Output Sections</h2>
            </div>
            <div className="section-grid">
              {outputSections.map((section) => (
                <div key={section.key} className="section-row">
                  <input
                    aria-label={`${section.label} enabled`}
                    type="checkbox"
                    checked={analysis.sections[section.key].enabled}
                    onChange={(event) => updateSectionEnabled(section.key, event.target.checked)}
                  />
                  <span className="section-copy">
                    <strong>{section.label}</strong>
                    <small>
                      {formatDurationRange(
                        analysis.sections[section.key].duration_min_seconds,
                        analysis.sections[section.key].duration_max_seconds
                      )}
                    </small>
                  </span>
                  <span className="section-field">
                    <span>Min sec</span>
                    <input
                      aria-label={`${section.label} min seconds`}
                      min={1}
                      max={1800}
                      type="number"
                      value={analysis.sections[section.key].duration_min_seconds ?? ""}
                      onChange={(event) =>
                        updateSectionDuration(
                          section.key,
                          "duration_min_seconds",
                          event.target.value === "" ? null : Number(event.target.value)
                        )
                      }
                    />
                  </span>
                  <span className="section-field">
                    <span>Max sec</span>
                    <input
                      aria-label={`${section.label} max seconds`}
                      min={1}
                      max={1800}
                      type="number"
                      value={analysis.sections[section.key].duration_max_seconds ?? ""}
                      onChange={(event) =>
                        updateSectionDuration(
                          section.key,
                          "duration_max_seconds",
                          event.target.value === "" ? null : Number(event.target.value)
                        )
                      }
                    />
                  </span>
                  <span className="section-field">
                    <span>Count</span>
                    <input
                      aria-label={`${section.label} count`}
                      min={1}
                      max={10}
                      type="number"
                      value={analysis.sections[section.key].target_count}
                      onChange={(event) => updateSectionCount(section.key, Number(event.target.value))}
                    />
                  </span>
                </div>
              ))}
            </div>
            <label>
              Optional direction
              <textarea
                value={analysis.custom_instructions ?? ""}
                onChange={(event) => setAnalysis({ ...analysis, custom_instructions: event.target.value })}
                placeholder="Focus on AI governance, avoid salesy outputs"
              />
            </label>
            <button className="analysis-run-button" onClick={analyzeEpisode} disabled={!canAnalyze}>
              <WandSparkles size={16} />
              Run Analysis
            </button>
            {visibleAnalysisEvent && (
              <div className={`analysis-progress ${visibleAnalysisEvent.level}`} aria-live="polite">
                <div className="analysis-progress-head">
                  <strong>{analysisEventProgress(visibleAnalysisEvent)}%</strong>
                  <span>{visibleAnalysisEvent.message}</span>
                </div>
                <div
                  className="analysis-progress-track"
                  aria-label={`Analysis progress ${analysisEventProgress(visibleAnalysisEvent)}%`}
                >
                  <span style={{ width: `${analysisEventProgress(visibleAnalysisEvent)}%` }} />
                </div>
              </div>
            )}
          </section>

          <section className="panel board" id="board">
            <div className="board-head">
              <div className="panel-title">
                <Filter size={18} />
                <h2>Outputs</h2>
              </div>
              <div className="filters">
                <select value={purposeFilter} onChange={(event) => setPurposeFilter(event.target.value)}>
                  <option value="">All sections</option>
                  {outputSections.map((section) => (
                    <option key={section.key} value={section.targetPlatform}>
                      {section.label}
                    </option>
                  ))}
                </select>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="">All statuses</option>
                  <option value="recommended">Recommended</option>
                  <option value="approved">Approved</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
            </div>
            <div className="clip-list">
              {groupedOutputs.map((section) => (
                <div key={section.key} className="section-output-group">
                  <div className="section-output-title">{section.label}</div>
                  {section.items.map((clip) => (
                    <button
                      key={clip.id}
                      className={`clip-row ${selectedClip?.id === clip.id ? "active" : ""}`}
                      onClick={() => setSelectedClipId(clip.id)}
                    >
                      <span className="rank">{clip.rank}</span>
                      <span>
                        <strong>{clip.purpose} · {clip.moment_type.replace("_", " ")}</strong>
                        <small>
                          {formatTime(clip.start_seconds)}-{formatTime(clip.end_seconds)} ·{" "}
                          {Math.round(clip.duration_seconds)}s · {clip.status}
                        </small>
                      </span>
                    </button>
                  ))}
                </div>
              ))}
              {!clips.length && <div className="empty">No outputs yet</div>}
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
                    <h2>{selectedClip.purpose} {selectedClip.rank}</h2>
                    <p>
                      {selectedClip.moment_type.replace("_", " ")} ·{" "}
                      {formatTime(selectedClip.start_seconds)}-{formatTime(selectedClip.end_seconds)}
                    </p>
                  </div>
                </div>
                <p className="excerpt">{selectedClip.excerpt}</p>
                <p className="reasoning">{selectedClip.reasoning}</p>

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
                    <p className="render-hint">Upload a video or audio asset before rendering outputs.</p>
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
                  <button className="danger" onClick={() => setClipStatus(selectedClip, "rejected")} disabled={Boolean(busy)}>
                    <XCircle size={16} />
                    Reject
                  </button>
                  <button className="danger" onClick={() => deleteOutput(selectedClip)} disabled={Boolean(busy)}>
                    <Trash2 size={16} />
                    Delete
                  </button>
                  <button
                    className="secondary"
                    onClick={() => renderClip(selectedClip)}
                    disabled={Boolean(busy) || !hasMediaAsset || renderTypes.length === 0}
                  >
                    <Play size={16} />
                    Render
                  </button>
                </div>

                {renderError && (
                  <p className="render-error" role="alert">
                    {renderError}
                  </p>
                )}

                <div className="render-list">
                  {selectedClip.rendered_clips.filter(showRenderedClip).map((rendered) =>
                    rendered.status === "completed" ? (
                      <a key={rendered.id} href={api.downloadRenderUrl(rendered.id)} target="_blank" rel="noreferrer">
                        {renderTypeLabel(rendered.render_type)} · {rendered.status}
                      </a>
                    ) : (
                      <div key={rendered.id} className={`render-item ${rendered.status}`}>
                        <span>{renderTypeLabel(rendered.render_type)} · {rendered.status}</span>
                        {rendered.error && <small>{rendered.error}</small>}
                      </div>
                    )
                  )}
                </div>
              </>
            ) : (
              <div className="empty">Select an output</div>
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

function analysisEventProgress(event: AnalysisEvent) {
  return typeof event.progress === "number" ? clampProgress(event.progress) : 0;
}

function isTerminalAnalysisEvent(event: AnalysisEvent) {
  return event.level === "error" || event.event_type.endsWith(".completed");
}

function isBeforeIsoTime(value: string, reference: string) {
  const time = Date.parse(value);
  const referenceTime = Date.parse(reference);
  return Number.isFinite(time) && Number.isFinite(referenceTime) && time < referenceTime;
}

function clampProgress(progress: number) {
  return Math.min(100, Math.max(0, Math.round(progress)));
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
