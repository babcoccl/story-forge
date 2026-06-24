"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listStories } from "@/lib/api";
import type { StoryListItem } from "@/lib/types";

const POLL_INTERVAL_MS = 15_000;

const STATUS_LABELS: Record<string, string> = {
  planning: "Planning",
  writing: "Writing",
  assembled: "Assembled",
  reviewing: "Reviewing",
  complete: "Complete",
  failed: "Failed",
  pending: "Pending",
};

const IS_IN_PROGRESS = new Set(["planning", "writing", "reviewing"]);

export default function HomePage() {
  const [stories, setStories] = useState<StoryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStories = () => {
    listStories()
      .then((data) => {
        setStories(
          [...data].sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )
        );
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchStories();
    const id = setInterval(fetchStories, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold">Your Stories</h1>
        <Link
          href="/generate"
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 transition-colors"
        >
          New Story
        </Link>
      </div>

      {/* Loading / Error */}
      {loading && <p className="text-gray-400">Loading stories&hellip;</p>}
      {error && <p className="text-red-400">{error}</p>}

      {/* Empty state */}
      {!loading && !error && stories.length === 0 && (
        <div className="rounded-2xl border border-dashed border-gray-700 py-24 text-center">
          <p className="text-gray-300 text-lg mb-4">No stories yet</p>
          <Link
            href="/generate"
            className="text-indigo-400 underline hover:text-indigo-300"
          >
            Generate your first story
          </Link>
        </div>
      )}

      {/* Story grid */}
      {!loading && stories.length > 0 && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {stories.map((story) => (
              <Link
                key={story.id}
                href={`/stories/${story.id}`}
                className="group rounded-xl border border-gray-800 bg-gray-900/50 p-5 hover:border-gray-600 transition-colors"
              >
                {/* Title + status */}
                <div className="flex items-start justify-between gap-3 mb-3">
                  <h2 className="font-semibold text-gray-100 group-hover:text-indigo-300 transition-colors line-clamp-2">
                    {story.title || "(untitled)"}
                  </h2>
                  <span className="shrink-0 rounded-full bg-gray-800 px-2.5 py-0.5 text-xs text-gray-400">
                    {IS_IN_PROGRESS.has(story.status) ? (
                      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-500 border-t-transparent" />
                    ) : (
                      STATUS_LABELS[story.status] ?? story.status
                    )}
                  </span>
                </div>

                {/* Meta line */}
                <div className="flex gap-4 text-xs text-gray-500">
                  <span>{story.chapter_count} chapters</span>
                  <span>
                    {story.actual_word_count
                      ? `${(story.actual_word_count / 1000).toFixed(1)}k words`
                      : "0 words"}
                  </span>
                  <span>{new Date(story.created_at).toLocaleDateString()}</span>
                </div>
              </Link>
            ))}
          </div>

          {/* Footer */}
          <p className="mt-6 text-xs text-gray-400 text-center">
            {stories.length} {stories.length === 1 ? "story" : "stories"} total
          </p>
        </>
      )}
    </main>
  );
}