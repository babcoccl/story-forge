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
  actual_word_count: number | null;
  story_bible: Record<string, unknown> | null;
  chapter_count: number;
  scene_count: number;
  error_message: string | null;
  created_at: string;
}

export interface StoryCreateRequest {
  mode: StoryMode;
  seed?: string | null;
  overrides?: Record<string, string>;
  target_word_count?: number;
}

/** Lightweight story card for the home-page grid */
export interface StoryListItem {
  id: string;
  title: string | null;
  status: StoryStatus;
  actual_word_count: number | null;
  chapter_count: number;
  created_at: string;
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

// ---------------------------------------------------------------------------
// Chapter Reader types (Phase 8c)
// ---------------------------------------------------------------------------

/** Mirrors backend/app/schemas/story.py SceneResponse */
export interface SceneResponse {
  id: string;
  scene_number: number;
  beat: string | null;
  content: string | null;
  word_count: number | null;
  status: string;
  continuity_notes: string | null;
  revision_count: number;
}

/** Mirrors backend/app/schemas/story.py ChapterResponse */
export interface ChapterResponse {
  id: string;
  chapter_number: number;
  title: string | null;
  outline: string | null;
  content: string | null;
  word_count: number | null;
  status: string;
  scenes: SceneResponse[];
}

/** Mirrors backend/app/schemas/story.py ChapterListResponse */
export interface ChapterListResponse {
  story_id: string;
  chapter_count: number;
  chapters: ChapterResponse[];
}

/** Lightweight status check for polling during generation */
export interface StoryStatusResponse {
  id: string;
  status: StoryStatus;
  title: string | null;
  actual_word_count: number | null;
  error_message: string | null;
  chapter_statuses: string[];
}
