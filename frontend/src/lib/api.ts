/**
 * StoryForge API client.
 *
 * All backend calls go through this module. The base URL is read from
 * NEXT_PUBLIC_API_URL so it works in dev (localhost:8000) and production
 * without code changes.
 */

import type {
  AgentRunLogResponse,
  ChapterListResponse,
  StoryCostResponse,
  StoryCreateRequest,
  StoryListItem,
  StoryListResponse,
  StoryPerformanceResponse,
  StoryResponse,
  StoryStatusResponse,
} from "./types";

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

/**
 * GET /api/v1/stories/{storyId}/chapters/ — fetch all chapters with scenes.
 */
export async function getChapters(storyId: string): Promise<ChapterListResponse> {
  const res = await fetch(`${API_BASE}/stories/${storyId}/chapters/`);
  if (!res.ok) {
    throw new Error(`Failed to fetch chapters (${res.status})`);
  }
  return res.json() as Promise<ChapterListResponse>;
}

/**
 * GET /api/v1/stories/{storyId}/status — lightweight status check.
 */
export async function getStoryStatus(storyId: string): Promise<StoryStatusResponse> {
  const res = await fetch(`${API_BASE}/stories/${storyId}/status`);
  if (!res.ok) {
    throw new Error(`Failed to fetch status (${res.status})`);
  }
  return res.json() as Promise<StoryStatusResponse>;
}

/**
 * GET /api/v1/stories/ — list all stories (lightweight cards).
 */
export async function listStories(
  offset = 0,
  limit = 50,
): Promise<StoryListItem[]> {
  const res = await fetch(
    `${API_BASE}/stories/?offset=${offset}&limit=${limit}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to list stories (${res.status})`);
  }
  const data = (await res.json()) as StoryListResponse;
  return data.items;
}

/**
 * GET /api/v1/stories/{storyId}/cost
 * Returns aggregated token usage and optional cost estimate.
 */
export async function getStoryCost(storyId: string): Promise<StoryCostResponse> {
  const res = await fetch(`${API_BASE}/stories/${storyId}/cost`);
  if (!res.ok) {
    throw new Error(`Failed to fetch cost data (${res.status})`);
  }
  return res.json() as Promise<StoryCostResponse>;
}

/**
 * GET /api/v1/stories/{storyId}/agent-runs
 * Returns paginated AgentRun log for a story.
 */
export async function getAgentRuns(
  storyId: string,
  offset = 0,
  limit = 50,
): Promise<AgentRunLogResponse> {
  const res = await fetch(
    `${API_BASE}/stories/${storyId}/agent-runs?offset=${offset}&limit=${limit}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch agent runs (${res.status})`);
  }
  return res.json() as Promise<AgentRunLogResponse>;
}

/**
 * GET /api/v1/stories/{storyId}/performance
 * Returns wall-clock and per-scene LLM timing breakdown.
 */
export async function getStoryPerformance(
  storyId: string,
): Promise<StoryPerformanceResponse> {
  const res = await fetch(`${API_BASE}/stories/${storyId}/performance`);
  if (!res.ok) {
    throw new Error(`Failed to fetch performance data (${res.status})`);
  }
  return res.json() as Promise<StoryPerformanceResponse>;
}
