/** Tiny text utilities for heuristic segmentation and enrichment. */

export const STOPWORDS = new Set(
  `a about above after again against all also am an and any are as at be because been before being below between
  both but by can could did do does doing down during each even ever every few for from further get gets getting got
  had has have having he her here hers herself him himself his how i if in into is it its itself just know let like
  lot lots make made many may maybe me might more most much must my myself no nor not now of off often on once one
  only or other our ours ourselves out over own really right said same say says see she should so some something
  still such than that thats the their theirs them themselves then there these they thing things think this those
  though through to too under until up upon us very want was way we well were what when where whether which while
  who whom why will with would yeah you your yours yourself going gonna actually basically kind sort okay oh um uh
  let's it's that's there's we're they're you're i'm don't doesn't didn't can't won't isn't aren't wasn't weren't
  i've we've you've they've i'll we'll you'll it'll he's she's what's here's
  first second third next another new old good great big small time times year years people way ways two three`
    .split(/\s+/)
    .filter(Boolean),
);

export function stem(word: string): string {
  let w = word;
  if (w.length > 5 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.length > 5 && w.endsWith("ing")) w = w.slice(0, -3);
  else if (w.length > 4 && w.endsWith("ed")) w = w.slice(0, -2);
  else if (w.length > 4 && w.endsWith("es") && !w.endsWith("ses")) w = w.slice(0, -2);
  else if (w.length > 3 && w.endsWith("s") && !w.endsWith("ss") && !w.endsWith("us")) w = w.slice(0, -1);
  return w;
}

export interface Token {
  stem: string;
  surface: string;
}

export function tokenize(text: string): Token[] {
  const out: Token[] = [];
  for (const m of text.toLowerCase().matchAll(/[a-z][a-z'’-]*[a-z]|[a-z]/g)) {
    const surface = m[0].replace(/[’]/g, "'");
    if (surface.length < 3 || STOPWORDS.has(surface)) continue;
    out.push({ stem: stem(surface.replace(/'s$/, "")), surface: surface.replace(/'s$/, "") });
  }
  return out;
}

export function termFreq(tokens: Token[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const t of tokens) m.set(t.stem, (m.get(t.stem) ?? 0) + 1);
  return m;
}

export function cosine(a: Map<string, number>, b: Map<string, number>): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (const [k, v] of a) {
    na += v * v;
    const w = b.get(k);
    if (w) dot += v * w;
  }
  for (const v of b.values()) nb += v * v;
  return na && nb ? dot / Math.sqrt(na * nb) : 0;
}

export function splitSentences(text: string): string[] {
  return text
    .replace(/\s+/g, " ")
    .split(/(?<=[.!?])\s+(?=["'“(]?[A-Z0-9])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

/** Title-case words that are entirely lower case; leave mixed case (names, acronyms) alone. */
export function titleCase(text: string): string {
  const small = new Set(["a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "via"]);
  return text
    .split(" ")
    .map((w, i) => (w === w.toLowerCase() && (i === 0 || !small.has(w)) ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function truncateAtWord(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const i = cut.lastIndexOf(" ");
  return `${(i > max * 0.5 ? cut.slice(0, i) : cut).replace(/[,;:\s-]+$/, "")}…`;
}
