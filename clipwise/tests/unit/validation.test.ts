import { describe, expect, it } from "vitest";
import { normalizeTags, normalizeTopic, validateClipDraft } from "@/lib/domain/validation";

const base = { title: "Why Rome debased its coins", hook: "Short hook", topic: "ancient rome", tags: "Rome, Money, rome" };

describe("validateClipDraft", () => {
  it("accepts a valid clip with timestamp strings", () => {
    const r = validateClipDraft({ ...base, start: "3:15", end: "4:44" });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value.startSeconds).toBe(195);
      expect(r.value.endSeconds).toBe(284);
      expect(r.value.tags).toEqual(["rome", "money"]);
    }
  });

  it("accepts numeric seconds", () => {
    expect(validateClipDraft({ ...base, start: 10, end: 70 }).ok).toBe(true);
  });

  it("rejects end <= start", () => {
    const equal = validateClipDraft({ ...base, start: "1:00", end: "1:00" });
    const before = validateClipDraft({ ...base, start: "2:00", end: "1:00" });
    expect(equal.ok).toBe(false);
    expect(before.ok).toBe(false);
    if (!before.ok) expect(before.errors.end).toMatch(/after the start/);
  });

  it("rejects negative timestamps", () => {
    const r = validateClipDraft({ ...base, start: -5, end: 30 });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.start).toMatch(/negative/);
    expect(validateClipDraft({ ...base, start: "-0:05", end: "0:30" }).ok).toBe(false);
  });

  it("rejects malformed input", () => {
    for (const bad of [
      { ...base, start: "abc", end: "1:00" },
      { ...base, start: "0:10", end: "1:75" },
      { ...base, start: undefined, end: "1:00" },
      { ...base, start: {}, end: [] },
      { ...base, start: Number.NaN, end: 10 },
      { ...base, title: "   ", start: "0:10", end: "1:00" },
      { ...base, title: "x".repeat(200), start: "0:10", end: "1:00" },
      { ...base, start: "0:10", end: "0:12" }, // too short
      { ...base, start: "0:00", end: "2:00:00" }, // too long
    ]) {
      expect(validateClipDraft(bad).ok).toBe(false);
    }
  });

  it("rejects clips that end past the known video duration", () => {
    const r = validateClipDraft({ ...base, start: "1:00", end: "5:00" }, { videoDurationSeconds: 200 });
    expect(r.ok).toBe(false);
  });
});

describe("normalizers", () => {
  it("normalizes tags", () => {
    expect(normalizeTags(" A,b ,, a,#c")).toEqual(["a", "b", "c"]);
    expect(normalizeTags(["X", 3, "y"])).toEqual(["x", "y"]);
  });
  it("normalizes topics", () => {
    expect(normalizeTopic("economic history")).toBe("Economic History");
    expect(normalizeTopic("science and technology")).toBe("Science and Technology");
    expect(normalizeTopic("AI safety")).toBe("AI Safety");
  });
});
