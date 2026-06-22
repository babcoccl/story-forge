/**
 * StoryForge API client.
 *
 * All backend calls go through this module. The base URL is read from
 * NEXT_PUBLIC_API_URL so it works in dev (localhost:8000) and production
 * without code changes.
 */

import type { StoryCreateRequest, StoryResponse } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const API_BASE = `${BASE_URL}/api/v1`;

/**
 * POST /api/v1/stories/ — create and begin generating a new story.
 * Returns the initial StoryResponse (status will be "planning").
 */
export async function createStory(
  request: StoryCreateRequest
): Promise<StoryResponse> {
  const res = await fetch(`${API_BASE}/stories/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Failed to create story (${res.status}): ${detail}`);
  }
  return res.json() as Promise<StoryResponse>;
}

/**
 * GET /api/v1/stories/{storyId} — fetch story details.
 */
export async function getStory(storyId: string): Promise<StoryResponse> {
  const res = await fetch(`${API_BASE}/stories/${storyId}`);
  if (!res.ok) {
    throw new Error(`Story not found (${res.status})`);
  }
  return res.json() as Promise<StoryResponse>;
}

/**
 * Returns the SSE stream URL for a story.
 * The caller opens an EventSource with this URL.
 */
export function getStreamUrl(storyId: string): string {
  return `${API_BASE}/stories/${storyId}/stream`;
}