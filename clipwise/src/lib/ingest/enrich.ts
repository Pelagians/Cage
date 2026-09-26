/**
 * Heuristic enrichment: title, hook, summary, topic, tags and a quality prior for each
 * segment, using TF-IDF keywords and a small topic lexicon. Needs no network and no model.
 */
import type { Segment } from "./segment";
import { isHeadingCue } from "./segment";
import { splitSentences, termFreq, titleCase, tokenize, truncateAtWord, wordCount, type Token } from "./text";

export interface Enrichment {
  title: string;
  hook: string;
  summary: string;
  topic: string;
  tags: string[];
  qualityScore: number;
  lowValue: boolean;
  notes: string[];
}

const TOPIC_LEXICON: Record<string, string[]> = {
  "Ancient Rome": ["rome", "roman", "emperor", "empire", "denarius", "caesar", "legion", "senate", "diocletian", "augustus", "constantine", "republic", "gaul", "byzantine", "latin"],
  History: ["history", "historical", "century", "war", "king", "medieval", "ancient", "revolution", "dynasty", "civilization", "colonial", "battle", "reign"],
  Economics: ["economy", "economic", "inflation", "money", "currency", "debt", "credit", "price", "market", "tax", "interest", "bank", "recession", "gdp", "trade", "wage", "monetary", "fiscal", "debasement", "coin", "silver", "gold"],
  Business: ["startup", "company", "business", "customer", "revenue", "founder", "product", "profit", "strategy", "investor", "competition", "marketing", "growth"],
  Physics: ["physics", "energy", "entropy", "relativity", "quantum", "particle", "gravity", "light", "mass", "velocity", "thermodynamic", "heat", "temperature", "photon", "electron", "time", "dilation", "simultaneity"],
  Space: ["space", "planet", "star", "galaxy", "universe", "orbit", "sun", "moon", "mars", "cosmic", "black", "telescope", "astronaut", "solar"],
  Biology: ["cell", "gene", "dna", "evolution", "species", "protein", "organism", "immune", "virus", "bacteria", "brain", "neuron", "body", "life"],
  "Machine Learning": ["neural", "network", "learning", "model", "training", "gradient", "layer", "weight", "bias", "activation", "algorithm", "data", "ai", "deep"],
  Technology: ["computer", "software", "internet", "chip", "transistor", "code", "digital", "engineering", "technology", "device", "gps", "satellite", "battery"],
  Mathematics: ["math", "equation", "number", "function", "matrix", "vector", "proof", "probability", "geometry", "calculus", "theorem", "linear", "algebra"],
  Philosophy: ["philosophy", "meaning", "ethics", "moral", "existence", "consciousness", "free", "truth", "knowledge", "nihilism", "stoic", "virtue", "mind", "purpose"],
  "Political Power": ["power", "ruler", "dictator", "democracy", "government", "election", "vote", "politics", "political", "supporters", "regime", "leader", "state"],
  Psychology: ["psychology", "behavior", "habit", "emotion", "bias", "motivation", "memory", "attention", "stress", "happiness", "cognitive"],
};

export const LOW_VALUE = /\b(sponsor(ed)?|patreon|subscribe|brilliant\.org|squarespace|skillshare|nordvpn|audible|link in the description|thanks for watching|smash that|merch)\b/i;

const FILLER_START = /^(so|and|but|now|okay|ok|well|right|alright|um|uh|yeah)[,\s]+/i;

function cleanSentence(s: string): string {
  let t = s.trim();
  for (let i = 0; i < 2; i++) t = t.replace(FILLER_START, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function lexiconStem(word: string) {
  return tokenize(word)[0]?.stem ?? word;
}

const STEMMED_LEXICON: [string, Set<string>][] = Object.entries(TOPIC_LEXICON).map(([topic, words]) => [
  topic,
  new Set(words.map(lexiconStem)),
]);

export function classifyTopic(tokens: Token[], fallback?: string): string {
  const tf = termFreq(tokens);
  let bestTopic = fallback ?? "General";
  let bestScore = 0;
  for (const [topic, words] of STEMMED_LEXICON) {
    let score = 0;
    for (const w of words) score += Math.min(tf.get(w) ?? 0, 3);
    if (score > bestScore) {
      bestScore = score;
      bestTopic = topic;
    }
  }
  return bestScore >= 2 ? bestTopic : (fallback ?? "General");
}

/** Build IDF over segments so keywords are distinctive for their segment. */
export function makeIdf(segmentsTokens: Token[][]): (stem: string) => number {
  const df = new Map<string, number>();
  for (const toks of segmentsTokens) for (const s of new Set(toks.map((t) => t.stem))) df.set(s, (df.get(s) ?? 0) + 1);
  const n = segmentsTokens.length;
  return (s) => Math.log(1 + n / (1 + (df.get(s) ?? 0))) + 0.2;
}

const LEXICON_STEMS = new Set(STEMMED_LEXICON.flatMap(([, words]) => [...words]));
const WEAK_TAG_WORDS = new Set(
  "came become became stayed collected along away later afford went took found look looked turn turned started began means meant used using called keep keeps kept put puts tried trying try made making makes gave give given took taking seen seems seemed around whole part point fact case sure able across almost already always another anything anyway around back better cause certain clear close different doing done else enough entire especially exactly example fairly far fine following form full hard help high instead large last least less level likely little long low main mean needs never number often open order particular perhaps place possible pretty probably quite rather real reason simply since single slightly soon start step thought today together tried true turns usually various went whatever within without word work works world".split(" "),
);

export function keywords(tokens: Token[], idf: (s: string) => number, k = 6, properNouns: Set<string> = new Set()): string[] {
  const tf = termFreq(tokens);
  const surface = new Map<string, Map<string, number>>();
  for (const t of tokens) {
    const m = surface.get(t.stem) ?? new Map<string, number>();
    m.set(t.surface, (m.get(t.surface) ?? 0) + 1);
    surface.set(t.stem, m);
  }
  return [...tf]
    .filter(([s]) => s.length >= 3 && !WEAK_TAG_WORDS.has(s) && !WEAK_TAG_WORDS.has(`${s}s`))
    .map(([s, c]) => {
      let score = (1 + Math.log(c)) * idf(s);
      if (LEXICON_STEMS.has(s)) score *= 1.5;
      if (properNouns.has(s)) score *= 1.3;
      if (/(ed|ly)$/.test(s) && !LEXICON_STEMS.has(s)) score *= 0.3;
      return { s, score };
    })
    .sort((a, b) => b.score - a.score || a.s.localeCompare(b.s))
    .slice(0, k)
    .map(({ s }) => [...surface.get(s)!].sort((a, b) => b[1] - a[1])[0]![0]);
}

export function enrichSegmentHeuristically(
  segment: Segment,
  ctx: { idf: (s: string) => number; videoTopic?: string },
): Enrichment {
  const notes: string[] = [];
  const bodyCues = segment.cues.filter((c) => !isHeadingCue(c.text));
  const bodyText = bodyCues.map((c) => c.text).join(" ");
  const allText = segment.cues.map((c) => c.text).join(" ");
  const tokens = tokenize(allText);
  const properNouns = new Set(
    [...allText.matchAll(/(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b/g)].map((m) => tokenize(m[1]!)[0]?.stem ?? ""),
  );
  const kws = keywords(tokens, ctx.idf, 6, properNouns);
  const kwSet = new Set(kws.map((k) => tokenize(k)[0]?.stem ?? k));

  const sentences = splitSentences(bodyText).filter((s) => wordCount(s) >= 4);
  const scoreSentence = (s: string) => {
    const toks = tokenize(s);
    const hits = toks.filter((t) => kwSet.has(t.stem)).length;
    const wc = wordCount(s);
    const lengthFit = wc >= 8 && wc <= 30 ? 1 : wc < 8 ? 0.4 : 0.6;
    const question = /\?$/.test(s) ? 0.8 : 0;
    return hits * lengthFit + question;
  };
  const ranked = [...sentences].sort((a, b) => scoreSentence(b) - scoreSentence(a));

  let title: string;
  if (segment.heading) {
    title = titleCase(segment.heading.replace(/^(chapter|part|section)\s+\w+\s*[:.\-–—]\s*/i, "").replace(/[:\-–—]+$/, "").trim()) || segment.heading;
  } else {
    const titleSentence = ranked.find((s) => wordCount(s) <= 12) ?? ranked.find((s) => wordCount(s) <= 16) ?? ranked[0];
    if (titleSentence) {
      title = truncateAtWord(cleanSentence(titleSentence).replace(/[.!]$/, ""), 72);
    } else {
      title = titleCase(kws.slice(0, 3).join(", ")) || "Untitled segment";
    }
    notes.push("Title drafted from the transcript; consider rewriting it.");
  }

  const hookSentence = ranked.find((s) => !title.startsWith(cleanSentence(s).slice(0, 20)));
  const hook = hookSentence
    ? truncateAtWord(cleanSentence(hookSentence), 200)
    : kws.length
      ? `A closer look at ${kws.slice(0, 3).join(", ")}.`
      : "";

  let summary = "";
  for (const s of sentences) {
    const next = summary ? `${summary} ${s}` : s;
    if (next.length > 320) break;
    summary = next;
    if (summary.length > 200) break;
  }
  if (!summary && sentences[0]) summary = truncateAtWord(sentences[0], 320);

  const topic = classifyTopic(tokens, ctx.videoTopic);
  const promoCues = segment.cues.filter((c) => LOW_VALUE.test(c.text)).length;
  const lowValue = promoCues / segment.cues.length >= 0.4;
  if (lowValue) notes.push("Looks like a sponsor, intro or outro segment.");
  else if (promoCues) notes.push("Mentions a sponsor or 'subscribe'; you may want to trim it.");

  const duration = segment.end - segment.start;
  let quality = 0.55;
  if (segment.heading) quality += 0.1;
  if (duration >= 60 && duration <= 240) quality += 0.1;
  if (segment.boundaryStrength > 2) quality += 0.05;
  if (lowValue) quality -= 0.3;
  if (wordCount(bodyText) < 20 && !segment.heading) quality -= 0.1;

  return {
    title,
    hook,
    summary,
    topic,
    tags: kws.slice(0, 4).map((k) => k.toLowerCase()),
    qualityScore: Math.round(Math.min(0.95, Math.max(0.1, quality)) * 100) / 100,
    lowValue,
    notes,
  };
}
