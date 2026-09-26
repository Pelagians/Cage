/**
 * Demo content.
 *
 * The six YouTube video IDs below are real, public educational videos. Their IDs
 * and titles were checked against public web indexes while this app was built.
 * YouTube itself was unreachable from the build environment, so embeddability
 * and exact durations couldn't be checked.
 *
 * TIMESTAMPS: clips marked `verified: true` use the video's own published chapter
 * markers. Every other clip boundary is an *approximate* estimate of where that
 * idea is discussed. Those clips show an "approximate timestamps" badge in Watch
 * mode, with an Edit link, so you can fix them in a few seconds.
 */

export interface SeedVideo {
  key: string;
  youtubeVideoId: string;
  title: string;
  /** Empty when unknown — refreshed from YouTube oEmbed the first time you watch it. */
  channel: string;
  durationSeconds: number | null;
  description: string;
}

export interface SeedClip {
  id: string;
  video: string;
  title: string;
  hook: string;
  summary: string;
  topic: string;
  tags: string[];
  start: string;
  end: string;
  quality: number;
  related: string[];
  verified: boolean;
}

export const SEED_VIDEOS: SeedVideo[] = [
  {
    key: "dalio",
    youtubeVideoId: "PHe0bXAIuk0",
    title: "How The Economic Machine Works by Ray Dalio",
    channel: "Principles by Ray Dalio",
    durationSeconds: 1860,
    description: "A 30-minute animated model of how credit, debt cycles and deleveragings drive the economy.",
  },
  {
    key: "rulers",
    youtubeVideoId: "rStL7niR7gs",
    title: "The Rules for Rulers",
    channel: "CGP Grey",
    durationSeconds: 1173,
    description: "How power actually works: key supporters, the treasure, and why no one rules alone. Based on The Dictator's Handbook.",
  },
  {
    key: "nn",
    youtubeVideoId: "aircAruvnKk",
    title: "But what is a neural network? | Deep learning chapter 1",
    channel: "3Blue1Brown",
    durationSeconds: 1120,
    description: "The structure of a neural network, introduced through recognising hand-written digits.",
  },
  {
    key: "entropy",
    youtubeVideoId: "DxL2HoqLbyA",
    title: "The Most Misunderstood Concept in Physics",
    channel: "Veritasium",
    durationSeconds: 1635,
    description: "Entropy, heat engines, and why a low-entropy Sun is what actually keeps life going.",
  },
  {
    key: "nihilism",
    youtubeVideoId: "MBRqu0YOH14",
    title: "Optimistic Nihilism",
    channel: "Kurzgesagt – In a Nutshell",
    durationSeconds: 386,
    description: "A short, subjective take on finding meaning in a universe that doesn't hand you one.",
  },
  {
    key: "rome",
    youtubeVideoId: "qrebO_9bhuM",
    title: "How Inflation Ruined the Roman Economy",
    channel: "",
    durationSeconds: null,
    description: "How third-century emperors cut the silver in their coins and set off a cycle of inflation.",
  },
];

export const SEED_CLIPS: SeedClip[] = [
  // ── Economics: Ray Dalio ────────────────────────────────────────────────
  {
    id: "seed-dalio-transactions",
    video: "dalio",
    title: "The economy is just transactions",
    hook: "Every economy, however big, is the sum of individual trades. Understand one transaction and you understand the machine.",
    summary: "Dalio's opening framing: a buyer exchanges money or credit with a seller for goods, services or financial assets. Add up all transactions and you get markets; add up the markets and you get the economy.",
    topic: "Economics",
    tags: ["macroeconomics", "markets", "money"],
    start: "0:00",
    end: "2:10",
    quality: 0.7,
    related: ["seed-dalio-credit", "seed-rome-debasement"],
    verified: false,
  },
  {
    id: "seed-dalio-credit",
    video: "dalio",
    title: "Why credit is the most important part of the economy",
    hook: "Credit is the biggest and most volatile part of the economy. It lets you spend more than you earn today, at the cost of spending less later.",
    summary: "Borrowing creates spending, and one person's spending is another person's income. Credit amplifies booms and busts because it pulls future spending into the present.",
    topic: "Economics",
    tags: ["credit", "debt", "macroeconomics"],
    start: "2:10",
    end: "5:40",
    quality: 0.85,
    related: ["seed-dalio-short-cycle", "seed-dalio-deleveraging"],
    verified: false,
  },
  {
    id: "seed-dalio-short-cycle",
    video: "dalio",
    title: "The short-term debt cycle, in one picture",
    hook: "Every 5–8 years, easy credit pushes spending faster than production, prices rise, rates go up, and the cycle turns.",
    summary: "The central bank's interest-rate lever drives the familiar business cycle: expansion with cheap credit, inflation, tightening, recession, then easing again.",
    topic: "Economics",
    tags: ["debt cycles", "interest rates", "central banks", "inflation"],
    start: "7:10",
    end: "10:20",
    quality: 0.8,
    related: ["seed-dalio-credit", "seed-dalio-deleveraging", "seed-rome-inflation"],
    verified: false,
  },
  {
    id: "seed-dalio-deleveraging",
    video: "dalio",
    title: "Four ways out of too much debt",
    hook: "When debt outgrows income there are only four levers: cut spending, restructure debt, redistribute wealth, or print money.",
    summary: "Dalio describes a deleveraging and the four tools societies use to get out of one. Some are deflationary and some are inflationary, and a 'beautiful' deleveraging balances them.",
    topic: "Economics",
    tags: ["debt", "deleveraging", "money printing", "inflation"],
    start: "15:30",
    end: "20:20",
    quality: 0.85,
    related: ["seed-rome-inflation", "seed-rulers-treasure", "seed-dalio-short-cycle"],
    verified: false,
  },

  // ── Political power: CGP Grey ───────────────────────────────────────────
  {
    id: "seed-rulers-no-one-rules-alone",
    video: "rulers",
    title: "No one rules alone",
    hook: "Even the most absolute king can't collect taxes or command armies by himself. Power is really a question of who the ruler must keep happy.",
    summary: "The core idea behind The Rules for Rulers: every leader depends on 'keys to power', meaning the people whose support they can't lose. That constraint explains most political behaviour.",
    topic: "Political Power",
    tags: ["power", "incentives", "political science"],
    start: "0:00",
    end: "2:45",
    quality: 0.85,
    related: ["seed-rulers-treasure", "seed-rulers-democracy"],
    verified: false,
  },
  {
    id: "seed-rulers-treasure",
    video: "rulers",
    title: "Control the treasure, keep the keys",
    hook: "A ruler's real job is to take money from the population and hand enough of it to the keys to stay in power.",
    summary: "Why rulers obsess over treasury control, and why paying the military and the elites always comes before paying for the citizens.",
    topic: "Political Power",
    tags: ["power", "taxation", "military", "incentives"],
    start: "4:20",
    end: "8:00",
    quality: 0.8,
    related: ["seed-rome-debasement", "seed-dalio-deleveraging", "seed-rulers-no-one-rules-alone"],
    verified: false,
  },
  {
    id: "seed-rulers-democracy",
    video: "rulers",
    title: "Why democracies look nicer: they have more keys",
    hook: "Democratic leaders aren't nobler. They need so many supporters that the cheapest way to reward them is roads, schools and public goods.",
    summary: "The same rules apply to presidents and dictators. What changes is how many keys there are, which changes what's rational to spend the treasure on.",
    topic: "Political Power",
    tags: ["democracy", "power", "public goods", "incentives"],
    start: "10:30",
    end: "14:00",
    quality: 0.8,
    related: ["seed-rulers-no-one-rules-alone"],
    verified: false,
  },

  // ── Machine learning: 3Blue1Brown ───────────────────────────────────────
  {
    id: "seed-nn-neurons",
    video: "nn",
    title: "A 'neuron' is just a number",
    hook: "Strip away the biology metaphor: each neuron in a network simply holds a value between 0 and 1.",
    summary: "3Blue1Brown sets up the digit-recognition network: 784 input neurons for pixel brightness, hidden layers, and 10 outputs, then explains what a neuron's 'activation' means.",
    topic: "Machine Learning",
    tags: ["neural networks", "deep learning", "ai"],
    start: "2:42",
    end: "5:31",
    quality: 0.8,
    related: ["seed-nn-layers", "seed-nn-edges"],
    verified: false,
  },
  {
    id: "seed-nn-layers",
    video: "nn",
    title: "Why neural networks have layers",
    hook: "The hope behind layers: pixels become edges, edges become loops and lines, and those become digits.",
    summary: "The intuition for why a layered structure might learn to recognise things hierarchically, and why that hope motivates the whole architecture.",
    topic: "Machine Learning",
    tags: ["neural networks", "deep learning", "abstraction"],
    start: "5:31",
    end: "8:38",
    quality: 0.8,
    related: ["seed-nn-edges", "seed-nn-matrix"],
    verified: false,
  },
  {
    id: "seed-nn-edges",
    video: "nn",
    title: "How a single neuron could detect an edge",
    hook: "Weights are a pattern the neuron looks for, and the bias sets how strong the match must be before it lights up.",
    summary: "The concrete mechanics: a weighted sum of the previous layer, a bias, and a squishing function. Picturing the weights as an image shows what the neuron is tuned to.",
    topic: "Machine Learning",
    tags: ["neural networks", "weights", "biases", "ai"],
    start: "8:38",
    end: "11:34",
    quality: 0.85,
    related: ["seed-nn-knobs", "seed-nn-matrix"],
    verified: true,
  },
  {
    id: "seed-nn-knobs",
    video: "nn",
    title: "13,002 knobs: what 'learning' really means",
    hook: "Counting the weights and biases shows that 'learning' just means finding good settings for thousands of dials.",
    summary: "Covers the 'Counting weights and biases' and 'How learning relates' chapters: the network is a function with ~13k parameters, and training is the search for values that work.",
    topic: "Machine Learning",
    tags: ["neural networks", "training", "parameters", "ai"],
    start: "11:34",
    end: "13:26",
    quality: 0.75,
    related: ["seed-nn-matrix", "seed-nn-edges"],
    verified: true,
  },
  {
    id: "seed-nn-matrix",
    video: "nn",
    title: "A whole layer is one matrix multiplication",
    hook: "The compact notation (weights as a matrix, activations as a vector) is why neural nets run so well on GPUs.",
    summary: "The 'Notation and linear algebra' chapter: rewriting every neuron's weighted sum as one matrix-vector product plus a bias vector, passed through a nonlinearity.",
    topic: "Machine Learning",
    tags: ["linear algebra", "neural networks", "math"],
    start: "13:26",
    end: "15:17",
    quality: 0.75,
    related: ["seed-nn-knobs", "seed-nn-edges"],
    verified: true,
  },

  // ── Physics: Veritasium ─────────────────────────────────────────────────
  {
    id: "seed-entropy-sun",
    video: "entropy",
    title: "What Earth actually gets from the Sun",
    hook: "Earth radiates away about as much energy as it receives, so the Sun isn't really giving us energy. It's giving us something else.",
    summary: "The puzzle that opens the video: if energy in roughly equals energy out, what does sunlight provide that makes life possible? The answer turns out to be low entropy.",
    topic: "Physics",
    tags: ["entropy", "thermodynamics", "energy"],
    start: "0:00",
    end: "2:20",
    quality: 0.85,
    related: ["seed-entropy-microstates", "seed-entropy-life"],
    verified: false,
  },
  {
    id: "seed-entropy-carnot",
    video: "entropy",
    title: "Carnot's perfect engine still wastes heat",
    hook: "Even an idealised, frictionless engine can't turn all of its heat into work. That limit is where entropy comes from.",
    summary: "Sadi Carnot's analysis of heat engines and the efficiency ceiling that depends only on hot and cold temperatures, which is the historical root of the second law.",
    topic: "Physics",
    tags: ["thermodynamics", "engines", "history of science", "entropy"],
    start: "2:40",
    end: "7:30",
    quality: 0.75,
    related: ["seed-entropy-microstates"],
    verified: false,
  },
  {
    id: "seed-entropy-microstates",
    video: "entropy",
    title: "Entropy is just counting arrangements",
    hook: "Energy spreads out not because of a mysterious force, but because there are overwhelmingly more ways for it to be spread out.",
    summary: "Boltzmann's statistical view: entropy measures how many microscopic arrangements match what we see, and why that makes the second law so reliable.",
    topic: "Physics",
    tags: ["entropy", "statistics", "probability", "thermodynamics"],
    start: "12:50",
    end: "16:40",
    quality: 0.85,
    related: ["seed-entropy-life", "seed-entropy-sun"],
    verified: false,
  },
  {
    id: "seed-entropy-life",
    video: "entropy",
    title: "Life is how the universe speeds up entropy",
    hook: "Living things take in low-entropy energy and shed high-entropy heat. Structure may exist because it spreads energy faster.",
    summary: "Connecting entropy to life and the far future of the universe, from photosynthesis to the heat death.",
    topic: "Physics",
    tags: ["entropy", "life", "cosmology", "universe"],
    start: "20:00",
    end: "24:30",
    quality: 0.7,
    related: ["seed-nihilism-freedom", "seed-entropy-sun"],
    verified: false,
  },

  // ── Philosophy: Kurzgesagt ──────────────────────────────────────────────
  {
    id: "seed-nihilism-dread",
    video: "nihilism",
    title: "Staring into cosmic insignificance",
    hook: "Seen from the scale of the universe, a human life looks vanishingly small. Is that terrifying, or freeing?",
    summary: "Kurzgesagt sets up the existential problem: the cosmos is vast and old, and nothing in it seems to care about us.",
    topic: "Philosophy",
    tags: ["meaning", "existentialism", "universe"],
    start: "0:00",
    end: "1:45",
    quality: 0.65,
    related: ["seed-nihilism-freedom", "seed-entropy-life"],
    verified: false,
  },
  {
    id: "seed-nihilism-freedom",
    video: "nihilism",
    title: "If nothing matters, you get to decide what does",
    hook: "Optimistic nihilism flips the dread around: without a cosmic purpose, the only principles that count are the ones you choose.",
    summary: "The video's central argument for treating a meaningless universe as permission rather than a verdict.",
    topic: "Philosophy",
    tags: ["meaning", "existentialism", "ethics", "nihilism"],
    start: "2:50",
    end: "5:30",
    quality: 0.75,
    related: ["seed-nihilism-dread", "seed-entropy-life"],
    verified: false,
  },

  // ── Ancient Rome ────────────────────────────────────────────────────────
  {
    id: "seed-rome-debasement",
    video: "rome",
    title: "Why emperors quietly shrank the silver in coins",
    hook: "Rome needed more money than it had silver, so emperors minted coins with less and less silver in them.",
    summary: "How currency debasement began as a quiet fiscal trick for paying soldiers and expenses without raising taxes.",
    topic: "Ancient Rome",
    tags: ["rome", "money", "inflation", "debasement", "economic history"],
    start: "0:00",
    end: "2:30",
    quality: 0.75,
    related: ["seed-rome-inflation", "seed-rulers-treasure", "seed-dalio-deleveraging"],
    verified: false,
  },
  {
    id: "seed-rome-inflation",
    video: "rome",
    title: "When money stops meaning anything",
    hook: "Once people realised the denarius was mostly bronze, prices exploded and the empire's economy began to seize up.",
    summary: "The consequences of third-century debasement: runaway prices, collapsing trust in coinage, and pressure toward payment in kind.",
    topic: "Ancient Rome",
    tags: ["rome", "inflation", "money", "economic history"],
    start: "2:30",
    end: "5:00",
    quality: 0.7,
    related: ["seed-rome-debasement", "seed-dalio-short-cycle", "seed-dalio-deleveraging"],
    verified: false,
  },
];
