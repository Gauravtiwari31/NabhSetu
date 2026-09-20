export function StatusChip({
  kind,
  children,
}: {
  kind: "ok" | "warn" | "bad" | "neutral" | "live" | "mock";
  children: string;
}) {
  return <span className={`chip chip-${kind}`}>{children}</span>;
}
