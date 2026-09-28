import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge conditional class names, letting later Tailwind utilities win.
 *
 * Only Tailwind's own scales are used as utilities here. The design system's
 * extra type size is the `micro` class in `src/index.css` rather than a
 * `text-xxs` utility, because `tailwind-merge` cannot tell a custom `text-*`
 * size from a `text-*` colour and would drop one of the two.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
