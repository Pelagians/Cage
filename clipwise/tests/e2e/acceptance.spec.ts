import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FAKE_YT = fs.readFileSync(path.join(__dirname, "fake-youtube.js"), "utf8");
const FIXTURE = fs.readFileSync(path.join(__dirname, "../fixtures/rome-transcript.txt"), "utf8");

interface ApiClip {
  id: string;
  title: string;
  topic: string;
  startSeconds: number;
  endSeconds: number;
  saved: boolean;
  source: { youtubeVideoId: string };
}

async function setup(page: Page) {
  await page.route("https://www.youtube.com/iframe_api", (r) => r.fulfill({ contentType: "text/javascript", body: FAKE_YT }));
  await page.route(/i\.ytimg\.com/, (r) => r.abort());
  page.on("pageerror", (err) => console.log("[pageerror]", err.message));
}

async function feedIndex(page: Page) {
  return page.getByTestId("feed").evaluate((el) => Math.round(el.scrollTop / el.clientHeight));
}

async function scrollFeedTo(page: Page, index: number) {
  await page.getByTestId("feed").evaluate((el, i) => el.scrollTo({ top: i * el.clientHeight, behavior: "instant" }), index);
  await expect.poll(() => feedIndex(page)).toBe(index);
}

function card(page: Page, index: number) {
  return page.locator(`article.feed-card[data-index="${index}"]`);
}

async function playerTime(page: Page) {
  return page.locator(".fake-yt").evaluate((el) => Number((el as HTMLElement).dataset.time));
}

async function api<T>(page: Page, url: string): Promise<T> {
  const res = await page.request.get(url);
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as T;
}

test("critical acceptance workflow", async ({ page }) => {
  await setup(page);

  let firstTitle = "";
  await test.step("1-3: app starts, database initialises, feed loads", async () => {
    await page.goto("/");
    await expect(card(page, 0)).toBeVisible();
    firstTitle = (await card(page, 0).locator("h2").textContent()) ?? "";
    expect(firstTitle.length).toBeGreaterThan(5);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  });

  await test.step("4: scroll through multiple concept cards", async () => {
    for (const i of [1, 2, 3]) {
      await scrollFeedTo(page, i);
      await expect(card(page, i).getByRole("button", { name: /^Watch / })).toBeInViewport();
    }
    // Keyboard navigation (desktop) also works.
    await page.keyboard.press("ArrowUp");
    await expect.poll(() => feedIndex(page)).toBe(2);
    // No YouTube players are created while browsing.
    expect(await page.evaluate(() => (window as unknown as { __ytCreated?: number }).__ytCreated ?? 0)).toBe(0);
  });

  // Choose the shortest clip among the next few cards so the segment ends quickly.
  const feed = (await api<{ clips: ApiClip[] }>(page, "/api/feed?seed=1")).clips;
  const domIds = await page.locator("article.feed-card").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.clipId));
  const dom = domIds.map((id) => feed.find((c) => c.id === id)).filter(Boolean) as ApiClip[];
  const target = dom.map((c, i) => ({ c, i })).sort((a, b) => a.c.endSeconds - a.c.startSeconds - (b.c.endSeconds - b.c.startSeconds))[0]!;

  await test.step("5-7: Watch opens the right video at the right timestamp", async () => {
    await scrollFeedTo(page, target.i);
    await card(page, target.i).getByRole("button", { name: /^Watch / }).click();
    await expect(page).toHaveURL(new RegExp(`/watch/${target.c.id}$`));
    await expect(page.getByTestId("watch-title")).toHaveText(target.c.title);
    await expect(page.locator(".fake-yt")).toHaveAttribute("data-video-id", target.c.source.youtubeVideoId);
    const log = await page.evaluate(() => (window as unknown as { __ytLog: unknown[][] }).__ytLog);
    const create = log.find((e) => e[0] === "create")!;
    expect(create[1]).toBe(target.c.source.youtubeVideoId);
    expect(create[2]).toBe(Math.floor(target.c.startSeconds));
    expect(create[3]).toBe("https://www.youtube-nocookie.com");
    await expect.poll(() => page.locator(".fake-yt").getAttribute("data-state")).toBe("1"); // playing
    const t = await playerTime(page);
    expect(t).toBeGreaterThanOrEqual(target.c.startSeconds - 1);
    expect(t).toBeLessThan(target.c.endSeconds);
  });

  await test.step("8-9: segment end detected, playback pauses, completion UI appears", async () => {
    await expect(page.getByTestId("completion")).toBeVisible({ timeout: 30_000 });
    const log = await page.evaluate(() => (window as unknown as { __ytLog: unknown[][] }).__ytLog);
    const pause = log.filter((e) => e[0] === "pause").at(-1)!;
    expect(pause[2] as number).toBeGreaterThanOrEqual(target.c.endSeconds - 0.5);
    // The player polls every 250 ms; at the fake player's 30× speed that is up to 7.5 s of
    // video time (at real 1× speed it is ≤ 0.25 s).
    expect(pause[2] as number).toBeLessThan(target.c.endSeconds + 0.25 * 30 + 1);
    for (const name of ["Next", "Continue original", "Go deeper", "Save", "More like this", "Less like this"]) {
      await expect(page.getByTestId("completion").getByRole("button", { name, exact: true })).toBeVisible();
    }
  });

  await test.step("10: Continue Original plays past the clip boundary", async () => {
    await page.getByRole("button", { name: "Continue original" }).click();
    await expect(page.getByTestId("completion")).toBeHidden();
    await expect(page.getByTestId("watch-mode")).toHaveText("Playing full video");
    await expect.poll(() => playerTime(page)).toBeGreaterThan(target.c.endSeconds + 10);
    await expect(page.getByTestId("completion")).toBeHidden();
  });

  await test.step("11: return to feed at the same position; player cleaned up", async () => {
    await page.getByRole("link", { name: "Back to feed" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect.poll(() => feedIndex(page)).toBe(target.i);
    expect(await page.evaluate(() => (window as unknown as { __ytActive: number }).__ytActive)).toBe(0);
  });

  let savedTitle = "";
  await test.step("12-13: save another clip; it appears under Saved", async () => {
    const i = target.i === 0 ? 1 : 0;
    await scrollFeedTo(page, i);
    savedTitle = (await card(page, i).locator("h2").textContent())!;
    await card(page, i).getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Saved");
    await expect(card(page, i).getByRole("button", { name: "Saved" })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("link", { name: "Saved" }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();
    await expect(page.getByRole("link", { name: savedTitle, exact: true })).toBeVisible();
  });

  let boostedTopic = "";
  await test.step("14-16: More Like This changes weights and the ranking", async () => {
    const before = await api<{ topics: { topic: string; affinity: number; trend: string }[] }>(page, "/api/topics");
    // Pick a topic that currently sits low in the ranking.
    const beforeFeed = (await api<{ clips: ApiClip[] }>(page, "/api/feed?seed=7")).clips;
    const avgRank = (clips: ApiClip[], topic: string) => {
      const ranks = clips.map((c, i) => (c.topic === topic ? i : -1)).filter((i) => i >= 0);
      return ranks.reduce((a, b) => a + b, 0) / ranks.length;
    };
    const topics = [...new Set(beforeFeed.map((c) => c.topic))].filter((t) => beforeFeed.filter((c) => c.topic === t).length >= 2);
    boostedTopic = topics.sort((a, b) => avgRank(beforeFeed, b) - avgRank(beforeFeed, a))[0]!;
    const rankBefore = avgRank(beforeFeed, boostedTopic);

    // Returning to the feed restores the position and re-ranks the cards below it.
    const refreshed = page.waitForResponse((r) => r.url().includes("/api/feed?exclude="));
    await page.getByRole("link", { name: "Feed" }).click();
    await refreshed;
    await expect(card(page, 0)).toBeVisible();
    const cards = await page.locator("article.feed-card").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.clipId));
    const clipIndex = cards.findIndex((id) => beforeFeed.find((c) => c.id === id)?.topic === boostedTopic);
    await scrollFeedTo(page, clipIndex);
    const moreCard = card(page, clipIndex);
    await expect(moreCard.locator("span").first()).toHaveText(boostedTopic);
    await moreCard.getByRole("button", { name: "More like this" }).click();
    await expect(page.getByRole("status")).toHaveText(`More ${boostedTopic} coming up`);

    const after = await api<{ topics: { topic: string; affinity: number; trend: string }[] }>(page, "/api/topics");
    const aff = (s: typeof before, t: string) => s.topics.find((x) => x.topic === t)!.affinity;
    expect(aff(after, boostedTopic)).toBeGreaterThan(aff(before, boostedTopic) + 0.3);
    expect(after.topics.find((x) => x.topic === boostedTopic)!.trend).toMatch(/up/);

    const afterFeed = (await api<{ clips: ApiClip[] }>(page, "/api/feed?seed=7")).clips;
    expect(avgRank(afterFeed, boostedTopic)).toBeLessThan(rankBefore);

    // The cards right after the current one were re-ranked in place.
    await expect
      .poll(async () => {
        const ids = await page.locator("article.feed-card").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.clipId));
        const upcoming = ids.slice(clipIndex + 1, clipIndex + 3);
        return upcoming.filter((id) => afterFeed.find((c) => c.id === id)?.topic === boostedTopic).length;
      })
      .toBeGreaterThanOrEqual(1);

    await page.getByRole("link", { name: "Topics" }).click();
    await expect(page.locator(`[data-topic="${boostedTopic}"]`)).toHaveAttribute("data-trend", /up/);
  });

  const editedTitle = "E2E: Why the army broke the budget";
  await test.step("17-22: ingest a transcript, edit and approve a candidate", async () => {
    await page.getByRole("link", { name: "Add" }).click();
    await page.getByLabel("YouTube URL").fill("https://www.youtube.com/watch?v=fNk_zzaMoSs&t=12s");
    await expect(page.getByText(/Video ID fNk_zzaMoSs/)).toBeVisible();
    await page.getByLabel(/Video title/).fill("E2E test video");
    await page.getByLabel("Timestamped transcript").fill(FIXTURE);
    await page.getByRole("button", { name: "Generate candidate clips" }).click();
    await expect(page.getByTestId("review")).toBeVisible();
    const candidates = page.getByTestId("candidate");
    expect(await candidates.count()).toBeGreaterThanOrEqual(3);

    // Candidates show all the fields to review.
    const armyCandidate = candidates.filter({ has: page.locator('input[id$="-start"][value="4:00"]') });
    await expect(armyCandidate).toHaveCount(1);
    await expect(armyCandidate.getByLabel("Title")).toHaveValue("Why the Army Became So Expensive");
    await expect(armyCandidate.getByLabel("Hook")).not.toHaveValue("");
    await expect(armyCandidate.getByLabel("Topic")).not.toHaveValue("");
    await expect(armyCandidate.getByLabel("Summary")).not.toHaveValue("");
    await expect(armyCandidate.getByLabel("End")).toHaveValue("5:48");

    // Delete one candidate.
    const before = await candidates.count();
    await candidates.first().getByRole("button", { name: /Delete clip/ }).click();
    await expect(candidates).toHaveCount(before - 1);

    // Invalid edit is caught before saving.
    await armyCandidate.getByLabel("Title").fill(editedTitle);
    await armyCandidate.getByLabel("End").fill("3:00");
    await armyCandidate.getByRole("button", { name: "Approve" }).click();
    await page.getByRole("button", { name: /Save 1 approved clip/ }).click();
    await expect(armyCandidate.getByText("End time must be after the start time.")).toBeVisible();

    await armyCandidate.getByLabel("End").fill("5:40");
    await armyCandidate.getByLabel("Hook").fill("The legions cost more every year, and emperors couldn't say no.");
    await expect(armyCandidate.getByRole("button", { name: "Approved" })).toBeVisible();
    await page.getByRole("button", { name: /Save 1 approved clip/ }).click();
    await expect(page.getByTestId("ingest-success")).toBeVisible();
    await expect(page.getByTestId("ingest-success")).toContainText("Saved 1 clip");
  });

  await test.step("23: the approved clip appears in the feed", async () => {
    await page.getByRole("link", { name: "Open feed" }).click();
    await expect(card(page, 0)).toBeVisible();
    await expect(page.locator("article.feed-card h2", { hasText: editedTitle })).toHaveCount(1);
    const clip = (await api<{ clips: ApiClip[] }>(page, "/api/feed")).clips.find((c) => c.title === editedTitle)!;
    expect(clip.startSeconds).toBe(240);
    expect(clip.endSeconds).toBe(340);
    expect(clip.source.youtubeVideoId).toBe("fNk_zzaMoSs");
  });

  await test.step("24-25: data persists across a reload", async () => {
    await page.reload();
    await expect(card(page, 0)).toBeVisible();
    await expect(page.locator("article.feed-card h2", { hasText: editedTitle })).toHaveCount(1);
    await page.goto("/saved");
    await expect(page.getByRole("link", { name: savedTitle, exact: true })).toBeVisible();
    await page.goto("/topics");
    await expect(page.locator(`[data-topic="${boostedTopic}"]`)).toHaveAttribute("data-trend", /up/);
  });
});

test("Next and Go Deeper reuse one player and re-arm the boundary", async ({ page }) => {
  await setup(page);
  await page.goto("/watch/seed-rome-debasement");
  await expect(page.locator(".fake-yt")).toHaveAttribute("data-video-id", "qrebO_9bhuM");
  await expect(page.getByTestId("completion")).toBeVisible({ timeout: 30_000 });

  // Go Deeper lists related ideas; the explicitly linked follow-up comes first.
  await page.getByRole("button", { name: "Go deeper" }).click();
  const first = page.getByTestId("completion").locator("ul button").first();
  await expect(first).toContainText("When money stops meaning anything");
  await first.click();
  await expect(page).toHaveURL(/\/watch\/seed-rome-inflation$/);
  await expect(page.getByTestId("watch-title")).toHaveText("When money stops meaning anything");
  // Same video: the existing player seeks rather than being recreated.
  let log = await page.evaluate(() => (window as unknown as { __ytLog: unknown[][] }).__ytLog);
  expect(log.filter((e) => e[0] === "create")).toHaveLength(1);
  expect(log.some((e) => e[0] === "seek" && e[2] === 150)).toBe(true);
  await expect(page.getByTestId("completion")).toBeVisible({ timeout: 30_000 });

  // Next loads a different video in the same player, and the stale position right after
  // loading must not end the new segment immediately.
  await page.getByTestId("completion").getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByTestId("completion")).toBeHidden();
  await expect(page).not.toHaveURL(/seed-rome-inflation$/);
  await expect.poll(async () => (await page.evaluate(() => (window as unknown as { __ytLog: unknown[][] }).__ytLog)).some((e) => e[0] === "load" || e[0] === "seek")).toBe(true);
  await page.waitForTimeout(1500);
  await expect(page.getByTestId("completion")).toBeHidden();
  log = await page.evaluate(() => (window as unknown as { __ytLog: unknown[][] }).__ytLog);
  expect(log.filter((e) => e[0] === "create")).toHaveLength(1);
  expect(await page.evaluate(() => (window as unknown as { __ytActive: number }).__ytActive)).toBe(1);

  // Browser refresh lands on the clip now in the URL.
  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(page.locator(".fake-yt")).toBeVisible();
});

test("unavailable embedded video shows a friendly error", async ({ page }) => {
  await setup(page);
  // Create a source whose ID the fake player rejects with error 150 (embedding disabled).
  const res = await page.request.post("/api/sources", {
    data: { url: "https://youtu.be/errorVideo1", title: "Blocked video" },
    headers: { origin: "http://127.0.0.1:3100" },
  });
  expect(res.status()).toBe(201);
  const { source } = (await res.json()) as { source: { id: string } };
  const clipRes = await page.request.post("/api/clips", {
    data: { sourceId: source.id, title: "Blocked clip", start: "0:10", end: "1:00", topic: "Test" },
    headers: { origin: "http://127.0.0.1:3100" },
  });
  const { clip } = (await clipRes.json()) as { clip: { id: string } };
  await page.goto(`/watch/${clip.id}`);
  await expect(page.getByTestId("player-error")).toContainText("doesn't allow this video to be embedded");
  await expect(page.getByRole("link", { name: "Open on YouTube" }).first()).toBeVisible();
  const del = await page.request.delete(`/api/sources/${source.id}`, { headers: { origin: "http://127.0.0.1:3100" } });
  expect(del.status()).toBe(200);
});

test("validation and error handling on ingest and manual clips", async ({ page }) => {
  await setup(page);
  await page.goto("/ingest");
  await page.getByLabel("YouTube URL").fill("https://vimeo.com/12345");
  await expect(page.getByText(/doesn’t look like a YouTube video URL/)).toBeVisible();
  await page.getByRole("button", { name: "Generate candidate clips" }).click();
  await expect(page.getByText("That doesn't look like a YouTube video URL.")).toBeVisible();
  await expect(page.getByText(/Paste a timestamped transcript/)).toBeVisible();

  await page.getByLabel("YouTube URL").fill("https://youtu.be/fNk_zzaMoSs");
  await page.getByLabel("Timestamped transcript").fill("no timestamps here\njust words");
  await page.getByRole("button", { name: "Generate candidate clips" }).click();
  await expect(page.getByText(/No timestamps found/)).toBeVisible();

  // Manual clip: bad timestamps are rejected with clear messages.
  await page.getByRole("tab", { name: "Manual clip" }).click();
  await page.locator("#man-title").fill("Manual test clip");
  await page.locator("#man-start").fill("2:00");
  await page.locator("#man-end").fill("1:00");
  await page.getByRole("button", { name: "Save clip" }).click();
  await expect(page.getByText("End time must be after the start time.")).toBeVisible();
  await page.locator("#man-start").fill("abc");
  await page.getByRole("button", { name: "Save clip" }).click();
  await expect(page.getByText(/Start time isn't a valid timestamp/)).toBeVisible();

  // A valid manual clip saves against an existing source video.
  await page.locator("#man-start").fill("1:00");
  await page.locator("#man-end").fill("2:30");
  await page.locator("#man-hook").fill("A manual hook.");
  await page.locator("#man-topic").fill("testing");
  await page.getByRole("button", { name: "Save clip" }).click();
  await expect(page.getByTestId("manual-success")).toContainText("Manual test clip");
});

test("cross-site requests to the local API are blocked", async ({ page }) => {
  const res = await page.request.post("/api/admin/reset-demo", {
    data: {},
    headers: { origin: "https://evil.example" },
  });
  expect(res.status()).toBe(403);
  const form = await page.request.post("/api/admin/clear-history", {
    data: "x=1",
    headers: { "content-type": "application/x-www-form-urlencoded" },
  });
  expect(form.status()).toBe(415);
});
