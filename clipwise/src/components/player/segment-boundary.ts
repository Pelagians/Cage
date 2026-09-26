/**
 * Decides when the selected segment has ended. Pure logic, unit tested.
 *
 * It only "arms" once the playhead has been observed inside the segment. Straight
 * after a load or seek the player can still report the previous position, and without
 * arming that stale reading could end a clip the moment it starts.
 */
export class SegmentBoundary {
  private armed = false;
  private fired = false;
  enabled = true;

  constructor(
    private start: number,
    private end: number,
  ) {}

  reset(start: number, end: number) {
    this.start = start;
    this.end = end;
    this.armed = false;
    this.fired = false;
  }

  setEnd(end: number) {
    this.end = end;
  }

  get hasFired() {
    return this.fired;
  }

  /** Feed the current time; returns true exactly once, when the end is reached. */
  update(currentTime: number, playing: boolean): boolean {
    if (!this.enabled || this.fired || !playing || !Number.isFinite(currentTime)) return false;
    if (!this.armed) {
      if (currentTime >= this.start - 1.5 && currentTime < this.end - 0.3) this.armed = true;
      else return false;
    }
    if (currentTime >= this.end - 0.15) {
      this.fired = true;
      return true;
    }
    return false;
  }

  /** The whole video ended before our end marker (e.g. end set past the real length). */
  videoEnded(): boolean {
    if (!this.enabled || this.fired) return false;
    this.fired = true;
    return true;
  }
}
