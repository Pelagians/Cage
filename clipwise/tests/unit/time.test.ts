import { describe, expect, it } from "vitest";
import { formatDuration, formatTimestamp, parseTimestamp } from "@/lib/domain/time";

describe("parseTimestamp", () => {
  it.each([
    ["1:25", 85],
    ["01:25", 85],
    ["1:02:11", 3731],
    ["01:02:11", 3731],
    ["0:00", 0],
    ["00:01:25,500", 85.5],
    ["00:01:25.5", 85.5],
    ["85", 85],
    ["85s", 85],
    ["1m25s", 85],
    ["1h2m11s", 3731],
    [" 2:05 ", 125],
  ])("parses %s → %d", (input, expected) => {
    expect(parseTimestamp(input)).toBe(expected);
  });

  it.each(["", "abc", "1:75", "1:60:00", "-1:00", "1::2", "1:2:3:4", "12:3a", ":30", null, undefined])(
    "rejects %s",
    (input) => {
      expect(parseTimestamp(input as string)).toBeNull();
    },
  );
});

describe("formatting", () => {
  it("formats timestamps", () => {
    expect(formatTimestamp(85)).toBe("1:25");
    expect(formatTimestamp(3731)).toBe("1:02:11");
    expect(formatTimestamp(5.9)).toBe("0:05");
  });
  it("formats durations", () => {
    expect(formatDuration(134)).toBe("2m 14s");
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(120)).toBe("2m");
    expect(formatDuration(3720)).toBe("1h 2m");
  });
});
