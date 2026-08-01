import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind class names with conflict resolution.
 * Use this for all dynamic className composition in components.
 */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
