/** Stable hue per topic so cards of the same topic share a tint. */
export function topicHue(topic: string): number {
  let h = 0;
  for (let i = 0; i < topic.length; i++) h = (h * 31 + topic.toLowerCase().charCodeAt(i)) >>> 0;
  return h % 360;
}
