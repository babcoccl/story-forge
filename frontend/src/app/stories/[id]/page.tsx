"use client";

/**
 * Story Reader page — /stories/[id]
 *
 * Fetches story metadata + chapter scene counts, then displays a scrollable
 * reading view grouped by chapter with collapsible scene blocks.
 *
 * Lightweight polling: refreshes every 15s while status is planning/writing.
 * After assembled/complete/failed it stops polling.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getAgentRuns, getChapters, getStory, getStoryCost } from "@/lib/api";
import type {
  AgentRunLogItem,
  ChapterListResponse,
  SceneResponse,
  StoryCostResponse,
  StoryStatus,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TERMINAL_STATUSES = new Set<StoryStatus>(["complete", "assembled", "failed"]);

function StatusBadge({ status }: { status: StoryStatus }) {
  const colors: Record<StoryStatus, string> = {
    planning: "bg-yellow-100 text-yellow-800",
    writing: "bg-blue-100 text-blue-800",
    reviewing: "bg-purple-100 text-purple-800",
    assembled: "bg-green-100 text-green-800",
    complete: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    pending: "bg-gray-100 text-gray-800",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${colors[status] ?? colors.pending}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Scene block
// ---------------------------------------------------------------------------

function SceneBlock({ scene }: { scene: SceneResponse }) {
  const [collapsed, setCollapsed] = useState(false);
  const text = scene.content ?? "";
  const wordCount =
    (scene.word_count ?? 0) > 0
      ? scene.word_count!
      : text.split(/\s+/).filter(Boolean).length;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      {/* Header */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Scene {scene.scene_number}
          </span>
          <span className="text-xs text-gray-400">{wordCount.toLocaleString()} words</span>
        </div>
        <span className="text-gray-400">{collapsed ? "▸" : "▾"}</span>
      </button>

      {/* Content */}
      {!collapsed && (
        <div className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">
          {text}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chapter group
// ---------------------------------------------------------------------------

function ChapterGroup({ chapter }: { chapter: ChapterListResponse["chapters"][number] }) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold tracking-tight text-gray-900">
        {chapter.title ?? `Chapter ${chapter.chapter_number}`}
      </h2>
      {chapter.scenes.map((scene) => (
        <SceneBlock key={scene.id} scene={scene} />
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Phase 11: Observability panel components
// ---------------------------------------------------------------------------

function CollapsiblePanel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-semibold text-gray-700">{title}</span>
        <span className="text-gray-400 text-xs">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="border-t border-gray-100 px-4 py-4">{children}</div>}
    </div>
  );
}

function TokenSummaryPanel({ cost }: { cost: StoryCostResponse }) {
  return (
    <CollapsiblePanel title="Token Usage">
      <div className="mb-4 flex flex-wrap gap-6 text-sm">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Input tokens</p>
          <p className="font-semibold text-gray-900">
            {cost.total_prompt_tokens.toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Output tokens</p>
          <p className="font-semibold text-gray-900">
            {cost.total_completion_tokens.toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Total tokens</p>
          <p className="font-semibold text-gray-900">
            {cost.total_tokens.toLocaleString()}
          </p>
        </div>
        {cost.estimated_cost_usd !== null && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide">Est. cost</p>
            <p className="font-semibold text-gray-900">
              ${cost.estimated_cost_usd.toFixed(4)}
            </p>
          </div>
        )}
      </div>

      {cost.breakdown.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="border-b border-gray-100 text-gray-500 uppercase tracking-wide">
                <th className="pb-2 pr-4">Agent</th>
                <th className="pb-2 pr-4 text-right">Calls</th>
                <th className="pb-2 pr-4 text-right">Input</th>
                <th className="pb-2 pr-4 text-right">Output</th>
                <th className="pb-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {cost.breakdown.map((row) => (
                <tr key={row.agent_name} className="border-b border-gray-50">
                  <td className="py-1.5 pr-4 font-medium text-gray-700">
                    {row.agent_name}
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {row.call_count}
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {row.prompt_tokens.toLocaleString()}
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {row.completion_tokens.toLocaleString()}
                  </td>
                  <td className="py-1.5 text-right text-gray-700 font-medium">
                    {row.total_tokens.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CollapsiblePanel>
  );
}

function AgentRunLogPanel({ runs }: { runs: AgentRunLogItem[] }) {
  return (
    <CollapsiblePanel title={`Agent Run Log (${runs.length})`}>
      {runs.length === 0 ? (
        <p className="text-xs text-gray-400">No agent runs recorded.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="border-b border-gray-100 text-gray-500 uppercase tracking-wide">
                <th className="pb-2 pr-4">Agent</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4 text-right">Latency</th>
                <th className="pb-2 pr-4 text-right">In</th>
                <th className="pb-2 pr-4 text-right">Out</th>
                <th className="pb-2 pr-4 text-right">Retries</th>
                <th className="pb-2 text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-gray-50">
                  <td className="py-1.5 pr-4 font-medium text-gray-700">
                    {run.agent_name}
                  </td>
                  <td className="py-1.5 pr-4">
                    <span
                      className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${
                        run.status === "complete"
                          ? "bg-green-100 text-green-700"
                          : run.status === "failed"
                            ? "bg-red-100 text-red-700"
                            : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {run.latency_ms != null ? `${(run.latency_ms / 1000).toFixed(1)}s` : "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {run.prompt_tokens?.toLocaleString() ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {run.completion_tokens?.toLocaleString() ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-500">
                    {run.retry_count}
                  </td>
                  <td className="py-1.5 text-right text-gray-400">
                    {new Date(run.created_at).toLocaleTimeString(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CollapsiblePanel>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function StoryReaderPage() {
  const params = useParams();
  const router = useRouter();
  const storyId = params.id as string;

  const [title, setTitle] = useState<string | null>(null);
  const [status, setStatus] = useState<StoryStatus>("pending");
  const [chapters, setChapters] = useState<ChapterListResponse["chapters"]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cost, setCost] = useState<StoryCostResponse | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRunLogItem[]>([]);

  // ---------------------------------------------------------------------------
  // Initial load
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const [story, chapterData] = await Promise.all([
          getStory(storyId),
          getChapters(storyId),
        ]);
        if (!cancelled) {
          setTitle(story.title ?? null);
          setStatus(story.status);
          setChapters(chapterData.chapters);
        }
        // Observability data — fire and forget, never block reader
        getStoryCost(storyId)
          .then((c) => { if (!cancelled) setCost(c); })
          .catch(() => undefined);
        getAgentRuns(storyId)
          .then((r) => { if (!cancelled) setAgentRuns(r.items); })
          .catch(() => undefined);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load story.");
        }
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [storyId]);

  // ---------------------------------------------------------------------------
  // Polling — refresh every 15s while non-terminal
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (TERMINAL_STATUSES.has(status)) return;

    const poll = async () => {
      try {
        const story = await getStory(storyId);
        setStatus(story.status);
        if (story.title) setTitle(story.title);
        // If chapters grew, refresh them
        const chapterData = await getChapters(storyId);
        setChapters(chapterData.chapters);
      } catch {
        // Ignore polling failures
      }
    };

    const interval = setInterval(poll, 15_000);
    return () => clearInterval(interval);
  }, [storyId, status]);

  // ---------------------------------------------------------------------------
  // Derived stats
  // ---------------------------------------------------------------------------

  const stats = useMemo(() => {
    const totalScenes = chapters.reduce((sum, ch) => sum + ch.scenes.length, 0);
    const totalWords = chapters.reduce(
      (sum, ch) =>
        sum +
        ch.scenes.reduce(
          (s, sc) =>
            s +
            ((sc.word_count ?? 0) > 0
              ? sc.word_count!
              : (sc.content ?? "").split(/\s+/).filter(Boolean).length),
          0,
        ),
      0,
    );
    return { totalScenes, totalWords };
  }, [chapters]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <Link
            href="/generate"
            className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-500 mb-2"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back to Generate
           </Link>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">
            {title ?? "Loading…"}
          </h1>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-800">{error}</p>
          <button
            onClick={() => router.push("/generate")}
            className="mt-2 text-sm font-medium text-red-600 hover:text-red-500"
          >
            ← Back to Generate
          </button>
        </div>
      )}

      {/* Stats bar */}
      {!error && (
        <div className="mb-8 flex flex-wrap items-center gap-3 text-sm text-gray-600">
          <span>{chapters.length} chapter{chapters.length !== 1 ? "s" : ""}</span>
          <span>·</span>
          <span>{stats.totalScenes} scene{stats.totalScenes !== 1 ? "s" : ""}</span>
          <span>·</span>
          <span>{stats.totalWords.toLocaleString()} words</span>
        </div>
      )}

      {/* Chapters */}
      {!error && chapters.length > 0 ? (
        <div className="space-y-10">
          {chapters.map((chapter) => (
            <ChapterGroup key={chapter.id} chapter={chapter} />
          ))}
        </div>
      ) : !error ? (
        <div className="flex flex-col items-center gap-4 py-16 text-gray-500">
          <svg className="h-10 w-10 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <p className="text-sm">Waiting for chapters to appear…</p>
        </div>
      ) : null}

      {/* Observability panels */}
      {!error && (
        <div className="mt-12 space-y-3">
          {cost !== null && <TokenSummaryPanel cost={cost} />}
          <AgentRunLogPanel runs={agentRuns} />
        </div>
      )}
    </main>
  );
}
