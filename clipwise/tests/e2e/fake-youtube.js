// Stand-in for https://www.youtube.com/iframe_api used by the E2E tests (YouTube is not
// reachable from CI/sandboxes). It mimics the parts of the IFrame API the app uses,
// runs time at SPEED× real time, and records every call in window.__ytLog.
(function () {
  var PS = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 };
  var SPEED = window.__ytSpeed || 30;
  var DURATION = 2400;
  window.__ytLog = window.__ytLog || [];
  window.__ytActive = window.__ytActive || 0;
  window.__ytCreated = window.__ytCreated || 0;

  function Player(el, opts) {
    var self = this;
    this.opts = opts;
    this.videoId = opts.videoId;
    this.t = Number((opts.playerVars && opts.playerVars.start) || 0);
    this.state = PS.UNSTARTED;
    this.staleUntil = 0;
    var box = document.createElement("div");
    box.className = "fake-yt";
    box.style.cssText = "width:100%;height:100%;background:#222;color:#aaa;font:12px monospace;display:flex;align-items:center;justify-content:center";
    el.replaceWith(box);
    this.el = box;
    window.__ytActive++;
    window.__ytCreated++;
    window.__ytLog.push(["create", opts.videoId, this.t, opts.host || ""]);
    this.timer = setInterval(function () { self._tick(); }, 50);
    setTimeout(function () {
      if (/^error/.test(self.videoId)) {
        opts.events && opts.events.onError && opts.events.onError({ data: 150, target: self });
        return;
      }
      opts.events && opts.events.onReady && opts.events.onReady({ target: self });
    }, 40);
  }
  Player.prototype._tick = function () {
    if (this.state === PS.PLAYING) {
      this.t += 0.05 * SPEED;
      if (this.t >= DURATION) {
        this.t = DURATION;
        this._set(PS.ENDED);
      }
    }
    this.el.textContent = this.videoId + " @ " + this.t.toFixed(1);
    this.el.dataset.videoId = this.videoId;
    this.el.dataset.time = String(this.t);
    this.el.dataset.state = String(this.state);
  };
  Player.prototype._set = function (s) {
    this.state = s;
    this.opts.events && this.opts.events.onStateChange && this.opts.events.onStateChange({ data: s, target: this });
  };
  Player.prototype.playVideo = function () { window.__ytLog.push(["play", this.videoId, this.t]); this._set(PS.PLAYING); };
  Player.prototype.pauseVideo = function () { window.__ytLog.push(["pause", this.videoId, this.t]); this._set(PS.PAUSED); };
  Player.prototype.seekTo = function (s) { window.__ytLog.push(["seek", this.videoId, s]); this.t = s; };
  Player.prototype.loadVideoById = function (o) {
    var self = this;
    window.__ytLog.push(["load", o.videoId, o.startSeconds || 0]);
    // Like the real player, keep reporting the old position for a moment after loading.
    var old = this.t;
    this.videoId = o.videoId;
    this.t = old;
    this._set(PS.BUFFERING);
    setTimeout(function () { self.t = o.startSeconds || 0; self._set(PS.PLAYING); }, 300);
  };
  Player.prototype.cueVideoById = function (o) {
    window.__ytLog.push(["cue", o.videoId, o.startSeconds || 0]);
    this.videoId = o.videoId;
    this.t = o.startSeconds || 0;
    this._set(PS.CUED);
  };
  Player.prototype.getCurrentTime = function () { return this.t; };
  Player.prototype.getDuration = function () { return DURATION; };
  Player.prototype.getPlayerState = function () { return this.state; };
  Player.prototype.destroy = function () {
    window.__ytLog.push(["destroy", this.videoId]);
    clearInterval(this.timer);
    window.__ytActive--;
    this.el.remove();
  };

  window.YT = { Player: Player, PlayerState: PS };
  setTimeout(function () { window.onYouTubeIframeAPIReady && window.onYouTubeIframeAPIReady(); }, 10);
})();
