import { describe, expect, it } from "vitest";
import { SegmentBoundary } from "@/components/player/segment-boundary";

describe("SegmentBoundary", () => {
  it("fires once when playback reaches the end", () => {
    const b = new SegmentBoundary(60, 90);
    expect(b.update(60.2, true)).toBe(false);
    expect(b.update(75, true)).toBe(false);
    expect(b.update(89.9, true)).toBe(true);
    expect(b.update(90.5, true)).toBe(false);
  });

  it("ignores stale positions before the playhead reaches the segment", () => {
    const b = new SegmentBoundary(60, 90);
    // Player still reports the previous clip's position (past our end) right after loading.
    expect(b.update(300, true)).toBe(false);
    expect(b.update(0, true)).toBe(false);
    expect(b.update(60, true)).toBe(false);
    expect(b.update(90, true)).toBe(true);
  });

  it("does nothing while paused or disabled (Continue Original)", () => {
    const b = new SegmentBoundary(0, 30);
    b.update(5, true);
    expect(b.update(31, false)).toBe(false);
    b.enabled = false;
    expect(b.update(31, true)).toBe(false);
    expect(b.videoEnded()).toBe(false);
  });

  it("resets for a new clip or a replay", () => {
    const b = new SegmentBoundary(0, 30);
    b.update(1, true);
    expect(b.update(30, true)).toBe(true);
    b.reset(0, 30);
    expect(b.hasFired).toBe(false);
    b.update(1, true);
    expect(b.update(30, true)).toBe(true);
  });

  it("treats the video ending early as the end of the segment", () => {
    const b = new SegmentBoundary(100, 400);
    expect(b.videoEnded()).toBe(true);
    expect(b.videoEnded()).toBe(false);
  });
});
