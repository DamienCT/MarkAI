const KEY = "selectedBrandId";

export function getStoredBrandValue(): string {
  if (typeof window === "undefined") return "all";
  return window.localStorage.getItem(KEY) || "all";
}

export function getStoredBrandId(): string | null {
  const v = getStoredBrandValue();
  return v === "all" ? null : v;
}

export function setStoredBrandValue(value: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, value);
}
