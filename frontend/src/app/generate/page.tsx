"use client";

/**
 * Generate page — /generate
 *
 * State machine:
 *   idle        → user fills out the generation form
 *   submitting  → POST /stories/ in flight (spinner)
 *   generating  → SSE stream open, live progress displayed
 *   done        → assembled event received, success summary
 *   error       → failed event or fetch error, error message + retry
 */

import { useEffect, useRef, useState } from "react";
import { createStory, getStory, getStreamUrl, getStoryStatus } from "@/lib/api";
import type {
  SseAssembledPayload,
  SseChapterCompletePayload,
  SseErrorPayload,
  SseSceneCompletePayload,
  StoryMode,
  StoryStatus,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PageState = "rehydrating" | "idle" | "submitting" | "generating" | "done" | "error";

interface SceneEvent {
  chapterNumber: number;
  sceneNumber: number;
  wordCount: number | null;
  totalWordsSoFar: number;
}

interface GenerationResult {
  storyId: string;
  title: string | null;
  actualWordCount: number | null;
  chapterCount: number;
}

// ---------------------------------------------------------------------------
// Status badge helper
// ---------------------------------------------------------------------------

function StatusBadge({ count, label }: { count: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-3 py-1 text-sm font-medium text-indigo-800">
      <span className="font-bold">{count}</span> {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Pipeline status badge
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<StoryStatus, string> = {
  planning: "bg-yellow-100 text-yellow-800",
  writing: "bg-blue-100 text-blue-800",
  reviewing: "bg-purple-100 text-purple-800",
  assembled: "bg-green-100 text-green-800",
  complete: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  pending: "bg-gray-100 text-gray-800",
};

function StatusBadgeComponent({ status }: { status: StoryStatus }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${STATUS_COLORS[status] ?? STATUS_COLORS.pending}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

// sessionStorage key for navigation state recovery
const ACTIVE_STORY_KEY = "storyforge_active_story_id";

export default function GeneratePage() {
  // Form state
  const [mode, setMode] = useState<StoryMode>("standalone");
  const [seed, setSeed] = useState("");
  const [wordCount, setWordCount] = useState(15000);

  // Page state machine
  const [pageState, setPageState] = useState<PageState>("rehydrating");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Generation progress
  const [storyId, setStoryId] = useState<string | null>(null);
  const [sceneEvents, setSceneEvents] = useState<SceneEvent[]>([]);
  const [completedChapters, setCompletedChapters] = useState<number[]>([]);
  const [result, setResult] = useState<GenerationResult | null>(null);

  // Pipeline status polling
  const [writingStatus, setWritingStatus] = useState<StoryStatus | null>(null);

  // SSE ref — held outside state to allow cleanup
  const eventSourceRef = useRef<EventSource | null>(null);

  // ---------------------------------------------------------------------------
  // Navigation state rehydration — MUST be first useEffect
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const savedId = sessionStorage.getItem(ACTIVE_STORY_KEY);
    if (!savedId) {
      setPageState("idle");
      return;
    }

    getStoryStatus(savedId)
      .then((statusResp) => {
        if (statusResp.status === "planning" || statusResp.status === "writing") {
          setStoryId(savedId);
          setPageState("generating");
        } else if (statusResp.status === "assembled" || statusResp.status === "complete") {
          return getStory(savedId).then((story) => {
            setResult({
              storyId: savedId,
              title: story.title ?? null,
              actualWordCount: story.actual_word_count,
              chapterCount: story.chapter_count,
            });
            setPageState("done");
            sessionStorage.removeItem(ACTIVE_STORY_KEY);
          });
        } else {
          setErrorMessage("Previous generation failed or could not be found.");
          setPageState("error");
          sessionStorage.removeItem(ACTIVE_STORY_KEY);
        }
      })
      .catch(() => {
        setErrorMessage("Previous generation failed or could not be found.");
        setPageState("error");
        sessionStorage.removeItem(ACTIVE_STORY_KEY);
      });
  }, []);

  // ---------------------------------------------------------------------------
  // SSE lifecycle
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (pageState !== "generating" || storyId === null) return;

    const url = getStreamUrl(storyId);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.addEventListener("scene_complete", (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as SseSceneCompletePayload;
      setSceneEvents((prev) => [...prev, {
        chapterNumber: payload.chapter_number,
        sceneNumber: payload.scene_number,
        wordCount: payload.word_count,
        totalWordsSoFar: payload.total_words_so_far,
      }]);
    });

    es.addEventListener("chapter_complete", (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as SseChapterCompletePayload;
      setCompletedChapters((prev) => [...prev, payload.chapter_number]);
    });

    es.addEventListener("assembled", (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as SseAssembledPayload;
      // Fetch the story to get the title
      fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/stories/${payload.story_id}`)
        .then((r) => r.json())
        .then((story) => {
          setResult({
            storyId: payload.story_id,
            title: story.title ?? null,
            actualWordCount: payload.actual_word_count,
            chapterCount: payload.chapter_count,
          });
          setPageState("done");
          sessionStorage.removeItem(ACTIVE_STORY_KEY);
          es.close();
        })
        .catch(() => {
          // Story fetch failed but generation succeeded — show partial result
          setResult({
            storyId: payload.story_id,
            title: null,
            actualWordCount: payload.actual_word_count,
            chapterCount: payload.chapter_count,
          });
          setPageState("done");
          sessionStorage.removeItem(ACTIVE_STORY_KEY);
          es.close();
        });
    });

    es.addEventListener("error", (e: MessageEvent) => {
      // This fires for our custom "error" event type, not EventSource network errors
      try {
        const payload = JSON.parse(e.data) as SseErrorPayload;
        setErrorMessage(payload.error_message);
      } catch {
        setErrorMessage("An unknown error occurred during generation.");
      }
      setPageState("error");
      sessionStorage.removeItem(ACTIVE_STORY_KEY);
      es.close();
    });

    // Network-level EventSource error (connection refused, 500, etc.)
    es.onerror = () => {
      setErrorMessage("Lost connection to the generation stream. The server may be restarting.");
      setPageState("error");
      sessionStorage.removeItem(ACTIVE_STORY_KEY);
      es.close();
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [pageState, storyId]);

  // ---------------------------------------------------------------------------
  // Status polling — refreshes DB status every 10s during generation
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (pageState !== "generating" || storyId === null) return;

    const poll = async () => {
      try {
        const status = await getStoryStatus(storyId);
        setWritingStatus(status.status);
      } catch {
        // Ignore polling failures — SSE is the primary signal
      }
    };

    poll();
    const interval = setInterval(poll, 10_000);
    return () => clearInterval(interval);
  }, [pageState, storyId]);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPageState("submitting");
    setErrorMessage(null);
    setSceneEvents([]);
    setCompletedChapters([]);
    setResult(null);
    setWritingStatus(null);

    try {
      const story = await createStory({
        mode,
        seed: seed.trim() || null,
        target_word_count: wordCount,
      });
      setStoryId(story.id);
      setPageState("generating");
      sessionStorage.setItem(ACTIVE_STORY_KEY, story.id);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to start generation.");
      setPageState("error");
    }
  }

  function handleReset() {
    setPageState("idle");
    setStoryId(null);
    setSceneEvents([]);
    setCompletedChapters([]);
    setResult(null);
    setErrorMessage(null);
    setWritingStatus(null);
    sessionStorage.removeItem(ACTIVE_STORY_KEY);
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="mb-8 text-3xl font-bold tracking-tight text-gray-900">
        Generate Story
      </h1>

      {/* ── REHYDRATING: Minimal spinner (no text) ── */}
      {pageState === "rehydrating" && (
        <div className="flex justify-center py-16">
          <svg
            className="h-10 w-10 animate-spin text-indigo-600"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12" cy="12" r="10"
              stroke="currentColor" strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v8H4z"
            />
          </svg>
        </div>
      )}

      {/* ── IDLE: Generation form ── */}
      {pageState === "idle" && (
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Mode */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Mode
            </label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as StoryMode)}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="standalone">Standalone</option>
              <option value="continuation">Continuation</option>
            </select>
          </div>

          {/* Seed */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Seed{" "}
              <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="e.g. gothic-horror-winter"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* Word count */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Target word count
            </label>
            <input
              type="number"
              value={wordCount}
              onChange={(e) => setWordCount(Number(e.target.value))}
              min={5000}
              max={60000}
              step={1000}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="mt-1 text-xs text-gray-500">
              Typical generation: 15,000 words takes ~15–25 minutes.
            </p>
          </div>

          <button
            type="submit"
            className="w-full rounded-md bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-offset-2"
          >
            Generate
          </button>
        </form>
      )}

      {/* ── SUBMITTING: Spinner ── */}
      {pageState === "submitting" && (
        <div className="flex flex-col items-center gap-4 py-16 text-gray-500">
          <svg
            className="h-10 w-10 animate-spin text-indigo-600"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12" cy="12" r="10"
              stroke="currentColor" strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v8H4z"
            />
          </svg>
          <p className="text-sm">Starting generation pipeline…</p>
        </div>
      )}

      {/* ── GENERATING: Live progress ── */}
      {pageState === "generating" && (
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <svg
              className="h-5 w-5 animate-spin text-indigo-600"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12" cy="12" r="10"
                stroke="currentColor" strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
            <span className="text-sm font-medium text-gray-700">
              Generating…
            </span>
            {writingStatus && <StatusBadgeComponent status={writingStatus} />}
          </div>

          {/* Stats badges */}
          <div className="flex flex-wrap gap-2">
            <StatusBadge count={sceneEvents.length} label="scenes written" />
            <StatusBadge count={completedChapters.length} label="chapters complete" />
            {sceneEvents.length > 0 && (
              <StatusBadge
                count={sceneEvents[sceneEvents.length - 1].totalWordsSoFar}
                label="words so far"
              />
            )}
          </div>

          {/* Scene event log */}
          {sceneEvents.length > 0 && (
            <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                Scene log
              </p>
              <ul className="space-y-1 text-sm text-gray-700 max-h-64 overflow-y-auto">
                {sceneEvents.map((ev, i) => (
                  <li key={i} className="flex justify-between">
                    <span>
                      Chapter {ev.chapterNumber}, Scene {ev.sceneNumber}
                    </span>
                    <span className="text-gray-500">
                      {ev.wordCount != null ? `${ev.wordCount.toLocaleString()} words` : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {sceneEvents.length === 0 && (
            <p className="text-sm text-gray-500">
              Waiting for the planner to finish… (this takes 1–3 minutes)
            </p>
          )}

          {/* Live preview link */}
          {storyId && (
            <a
              href={`/stories/${storyId}`}
              className="inline-flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-500"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              View Story (live)
            </a>
          )}
        </div>
      )}

      {/* ── DONE: Success ── */}
      {pageState === "done" && result !== null && (
        <div className="space-y-6">
          <div className="rounded-lg border border-green-200 bg-green-50 p-6">
            <h2 className="text-xl font-semibold text-green-900 mb-1">
              {result.title ?? "Story complete"}
            </h2>
            <p className="text-sm text-green-700">
              {result.actualWordCount != null
                ? `${result.actualWordCount.toLocaleString()} words`
                : ""}{" "}
              across {result.chapterCount} chapters
            </p>
          </div>

          <div className="flex gap-3">
            <a
              href={`/stories/${result.storyId}`}
              className="flex-1 rounded-md bg-indigo-600 px-4 py-2.5 text-center text-sm font-semibold text-white shadow-sm hover:bg-indigo-500"
            >
              Read Story
            </a>
            <button
              onClick={handleReset}
              className="rounded-md border border-gray-300 px-4 py-2.5 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50"
            >
              Generate Another
            </button>
          </div>
        </div>
      )}

      {/* ── ERROR ── */}
      {pageState === "error" && (
        <div className="space-y-6">
          <div className="rounded-lg border border-red-200 bg-red-50 p-6">
            <h2 className="text-lg font-semibold text-red-900 mb-1">
              Generation failed
            </h2>
            <p className="text-sm text-red-700">
              {errorMessage ?? "An unknown error occurred."}
            </p>
          </div>
          <button
            onClick={handleReset}
            className="w-full rounded-md border border-gray-300 px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Try Again
          </button>
        </div>
      )}
    </main>
  );
}