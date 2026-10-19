/** Calls for the review screen. Every one needs an admin (ADMIN_EMAILS). */
import { api } from "./api";
import type { AdminPage, AdminPageDetail } from "./types";

export type QueueView = "escalated" | "all";

export function reviewQueue(view: QueueView) {
  return api<AdminPage[]>(`/admin/review?show=${view}`);
}

export function searchPages(text: string) {
  return api<AdminPage[]>(`/admin/pages?q=${encodeURIComponent(text)}`);
}

export function pageDetail(pageId: string) {
  return api<AdminPageDetail>(`/admin/pages/${pageId}`);
}

function act(pageId: string, action: string, body: object) {
  return api<AdminPageDetail>(`/admin/pages/${pageId}/${action}`, {
    method: "POST",
    body,
  });
}

export const approvePage = (
  pageId: string,
  topics: string[],
  reason?: string,
) => act(pageId, "approve", { topics, reason: reason || null });

export const rejectPage = (pageId: string, reason: string) =>
  act(pageId, "reject", { reason });

export const removePage = (pageId: string, reason: string) =>
  act(pageId, "remove", { reason });

export const purgePage = (pageId: string, reason: string, confirmUrl: string) =>
  act(pageId, "purge", { reason, confirm_url: confirmUrl });
