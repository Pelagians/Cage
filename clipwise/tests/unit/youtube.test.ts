import { describe, expect, it } from "vitest";
import { extractStartFromUrl, extractYouTubeId } from "@/lib/domain/youtube";

const ID = "PHe0bXAIuk0";

describe("extractYouTubeId", () => {
  it.each([
    `https://www.youtube.com/watch?v=${ID}`,
    `https://youtube.com/watch?v=${ID}&t=42s`,
    `https://www.youtube.com/watch?feature=share&v=${ID}`,
    `http://m.youtube.com/watch?v=${ID}`,
    `https://youtu.be/${ID}`,
    `https://youtu.be/${ID}?si=abc123&t=10`,
    `https://www.youtube.com/embed/${ID}?start=30`,
    `https://www.youtube-nocookie.com/embed/${ID}`,
    `https://www.youtube.com/shorts/${ID}`,
    `https://www.youtube.com/live/${ID}`,
    `https://www.youtube.com/v/${ID}`,
    `youtube.com/watch?v=${ID}`,
    `youtu.be/${ID}`,
    ID,
  ])("extracts from %s", (url) => {
    expect(extractYouTubeId(url)).toBe(ID);
  });

  it.each([
    "",
    "not a url",
    "https://vimeo.com/123456",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/watch",
    "https://www.youtube.com/channel/UC123",
    "https://evil.com/watch?v=PHe0bXAIuk0",
    "https://youtube.com.evil.com/watch?v=PHe0bXAIuk0",
  ])("rejects %s", (url) => {
    expect(extractYouTubeId(url)).toBeNull();
  });
});

describe("extractStartFromUrl", () => {
  it("reads t and start parameters", () => {
    expect(extractStartFromUrl(`https://youtu.be/${ID}?t=90`)).toBe(90);
    expect(extractStartFromUrl(`https://youtube.com/watch?v=${ID}&t=1m30s`)).toBe(90);
    expect(extractStartFromUrl(`https://youtube.com/embed/${ID}?start=15`)).toBe(15);
    expect(extractStartFromUrl(`https://youtube.com/watch?v=${ID}`)).toBeNull();
  });
});
