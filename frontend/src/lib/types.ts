/**
 * Types mirroring backend/app/schemas/story.py
 * Keep in sync with the backend manually until Phase 12 adds codegen.
 */

// ---------------------------------------------------------------------------
// Story schemas
// ---------------------------------------------------------------------------

export type StoryMode = "standalone" | "continuation";

export type StoryStatus =
  | "planning"
  | "writing"
  | "assembled"
  | "reviewing"
  | "complete"
  | "failed"
  | "pending";

export interface StoryResponse {
  id: string;
  title: string | null;
  mode: StoryMode;
  status: StoryStatus;
  generation_seed: string | null;
  synopsis: string | null;
  target_word_count: number;
  story_bible: Record<string, unknown> | null;
  chapter_count: number;
  scene_count: number;
  created_at: string;
}

export interface StoryCreateRequest {
  mode: StoryMode;
  seed?: string | null;
  overrides?: Record<string, string>;
  target_word_count?: number;
}

// ---------------------------------------------------------------------------
// SSE event payloads
// ---------------------------------------------------------------------------

export interface SseConnectedPayload {
  story_id: string;
}

export interface SseSceneCompletePayload {
  chapter_number: number;
  scene_number: number;
  word_count: number | null;
  total_words_so_far: number;
}

export interface SseChapterCompletePayload {
  chapter_number: number;
  word_count: number | null;
}

export interface SseAssembledPayload {
  story_id: string;
  actual_word_count: number | null;
  chapter_count: number;
}

export interface SseErrorPayload {
  story_id: string;
  error_message: string;
}