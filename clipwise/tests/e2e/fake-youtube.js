// Stand-in for https://www.youtube.com/iframe_api used by the E2E tests (YouTube is not
// reachable from CI/sandboxes). It mimics the parts of the IFrame API the app uses,
// runs time at SPEED× real time, and records every call in window.__ytLog.
(() => {
  const PS = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 };
  const SPEED = window.__ytSpeed || 30;
  const DURATION = 2400;
  window.__ytLog = window.__ytLog || [];
  window.__ytActive = window.__ytActive || 0;
  window.__ytCreated = window.__ytCreated || 0;
  const log = (...entry) => window.__ytLog.push(entry);

  class Player {
    constructor(el, opts) {
      this.opts = opts;
      this.videoId = opts.videoId;
      this.t = Number(opts.playerVars?.start ?? 0);
      this.state = PS.UNSTARTED;
      const box = document.createElement("div");
      box.className = "fake-yt";
      box.style.cssText =
        "width:100%;height:100%;background:#222;color:#aaa;font:12px monospace;display:flex;align-items:center;justify-content:center";
      el.replaceWith(box);
      this.el = box;
      window.__ytActive++;
      window.__ytCreated++;
      log("create", opts.videoId, this.t, opts.host ?? "");
      this.timer = setInterval(() => this.tick(), 50);
      setTimeout(() => {
        // IDs starting with "error" behave like videos whose owner disabled embedding.
        if (this.videoId.startsWith("error")) opts.events?.onError?.({ data: 150, target: this });
        else opts.events?.onReady?.({ target: this });
      }, 40);
    }

    tick() {
      if (this.state === PS.PLAYING) {
        this.t += 0.05 * SPEED;
        if (this.t >= DURATION) {
          this.t = DURATION;
          this.set(PS.ENDED);
        }
      }
      this.el.textContent = `${this.videoId} @ ${this.t.toFixed(1)}`;
      this.el.dataset.videoId = this.videoId;
      this.el.dataset.time = String(this.t);
      this.el.dataset.state = String(this.state);
    }

    set(state) {
      this.state = state;
      this.opts.events?.onStateChange?.({ data: state, target: this });
    }

    playVideo() {
      log("play", this.videoId, this.t);
      this.set(PS.PLAYING);
    }

    pauseVideo() {
      log("pause", this.videoId, this.t);
      this.set(PS.PAUSED);
    }

    seekTo(seconds) {
      log("seek", this.videoId, seconds);
      this.t = seconds;
    }

    loadVideoById({ videoId, startSeconds = 0 }) {
      log("load", videoId, startSeconds);
      // Like the real player, keep reporting the old position for a moment after loading.
      this.videoId = videoId;
      this.set(PS.BUFFERING);
      setTimeout(() => {
        this.t = startSeconds;
        this.set(PS.PLAYING);
      }, 300);
    }

    cueVideoById({ videoId, startSeconds = 0 }) {
      log("cue", videoId, startSeconds);
      this.videoId = videoId;
      this.t = startSeconds;
      this.set(PS.CUED);
    }

    getCurrentTime() {
      return this.t;
    }

    getDuration() {
      return DURATION;
    }

    getPlayerState() {
      return this.state;
    }

    destroy() {
      log("destroy", this.videoId);
      clearInterval(this.timer);
      window.__ytActive--;
      this.el.remove();
    }
  }

  window.YT = { Player, PlayerState: PS };
  setTimeout(() => window.onYouTubeIframeAPIReady?.(), 10);
})();
